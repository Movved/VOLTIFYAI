import numpy as np
import pandas as pd
from flask import Flask, jsonify
from flask_cors import CORS
from scipy.io import loadmat
import xgboost as xgb
import joblib
import threading
import time
import os

app = Flask(__name__)
CORS(app)

# 1. Load Pre-trained Model and Configuration
print("Loading pre-trained XGBoost model for VoltifyAI...")
MODEL_PATH = 'XGBoost.pkl'
if os.path.exists(MODEL_PATH):
    model_data = joblib.load(MODEL_PATH)
    xgb_model = model_data['model']
    FAULT_LABELS = model_data.get('fault_labels', {0: 'Normal', 1: 'Short-Circuit', 2: 'Degradation', 3: 'Open Circuit', 4: 'Shadowing'})
    FEATURE_COLS = model_data.get('feature_cols', ['vdc1', 'idc1', 'irr', 'pvt', 'pdc1', 'perf_ratio1', 'irr_temp'])
    print(f"Model loaded. Expecting features: {FEATURE_COLS}")
else:
    print(f"Error: {MODEL_PATH} not found.")
    exit(1)

# Hardcoded clipping limits matching training dataset's 1st and 99th percentiles (for irr >= 10)
CLIP_LIMITS = {
    'vdc1': (208.0412, 334.7416),
    'idc1': (0.1092, 9.2619),
    'irr': (12.3037, 985.4991),
    'pvt': (6.2367, 56.2810),
    'pdc1': (25.7339, 2411.9149),
    'perf_ratio1': (0.2142, 2.7163),
    'irr_temp': (0.6326, 46.0238)
}

# 2. Load Datasets
print("Loading datasets...")
elec_data = loadmat('dataset_elec.mat')
amb_data = loadmat('dataset_amb.mat')

# Feature extraction for String 1 and Ambient
vdc = elec_data['vdc1'].flatten()
idc = elec_data['idc1'].flatten()
irr = amb_data['irr'].flatten()
pvt = amb_data['pvt'].flatten()

# Group indices by fault type for simulation jumping
y_true_all = amb_data['f_nv'].flatten().astype(int)
FAULT_INDICES = {}
for fid in range(5):
    # Prefer day-time indices for more realistic/dynamic telemetry values
    day_indices = np.where((y_true_all == fid) & (irr >= 10))[0]
    if len(day_indices) > 0:
        FAULT_INDICES[fid] = day_indices.tolist()
    else:
        FAULT_INDICES[fid] = np.where(y_true_all == fid)[0].tolist()

# Create a DataFrame for processing
df = pd.DataFrame({
    'vdc1': vdc,
    'idc1': idc,
    'irr': irr,
    'pvt': pvt
})

# 3. Iterative Global Loop Tracker
current_index = 0
data_lock = threading.Lock()

def telemetry_stream():
    global current_index
    total_rows = len(df)
    while True:
        with data_lock:
            # Advance by 100 rows to speed up the time progression in the dataset
            # (making changes in current and voltage visible to the user)
            current_index = (current_index + 100) % total_rows
        time.sleep(3)

# Start telemetry simulation thread
stream_thread = threading.Thread(target=telemetry_stream, daemon=True)
stream_thread.start()

@app.route('/api/telemetry', methods=['GET'])
def get_telemetry():
    global current_index
    with data_lock:
        row = df.iloc[current_index]
    
    vdc1 = float(row['vdc1'])
    idc1 = float(row['idc1'])
    irr_val = float(row['irr'])
    pvt_val = float(row['pvt'])
    
    eps = 1e-6
    pdc1 = vdc1 * idc1
    
    # Feature Engineering (matching training notebook)
    perf_ratio1 = pdc1 / (irr_val + eps)
    irr_temp = irr_val / (pvt_val + eps)
    
    features_dict = {
        'vdc1': vdc1,
        'idc1': idc1,
        'irr': irr_val,
        'pvt': pvt_val,
        'pdc1': pdc1,
        'perf_ratio1': perf_ratio1,
        'irr_temp': irr_temp
    }
    
    # Prediction: if night (irr_val < 10), it is Normal (0) without running inference
    if irr_val < 10:
        prediction = 0
        label_name = FAULT_LABELS.get(prediction, 'Normal')
    else:
        # Clip incoming features to training quantiles to handle outliers
        clipped_features = {}
        for col in FEATURE_COLS:
            val = features_dict[col]
            q1, q3 = CLIP_LIMITS[col]
            clipped_features[col] = max(q1, min(q3, val))
        
        # Prepare 2D input array for prediction
        X_raw = np.array([[clipped_features[col] for col in FEATURE_COLS]])
        
        # Predict
        prediction = int(xgb_model.predict(X_raw)[0])
        label_name = FAULT_LABELS.get(prediction, 'Unknown')
    
    return jsonify({
        'vdc': vdc1,
        'idc': idc1,
        'irr': irr_val,
        'pvt': pvt_val,
        'pdc': pdc1,
        'status_code': prediction,
        'status_label': label_name
    })

@app.route('/api/simulate/<int:fault_id>', methods=['POST'])
def simulate_fault(fault_id):
    global current_index
    if fault_id in FAULT_INDICES:
        indices = FAULT_INDICES[fault_id]
        new_index = int(np.random.choice(indices))
        with data_lock:
            current_index = new_index
        
        # Get the row at the new index
        row = df.iloc[current_index]
        vdc1 = float(row['vdc1'])
        idc1 = float(row['idc1'])
        irr_val = float(row['irr'])
        pvt_val = float(row['pvt'])
        pdc1 = vdc1 * idc1
        eps = 1e-6
        perf_ratio1 = pdc1 / (irr_val + eps)
        irr_temp = irr_val / (pvt_val + eps)
        
        features_dict = {
            'vdc1': vdc1,
            'idc1': idc1,
            'irr': irr_val,
            'pvt': pvt_val,
            'pdc1': pdc1,
            'perf_ratio1': perf_ratio1,
            'irr_temp': irr_temp
        }
        
        if irr_val < 10:
            prediction = 0
            label_name = FAULT_LABELS.get(prediction, 'Normal')
        else:
            clipped_features = {}
            for col in FEATURE_COLS:
                val = features_dict[col]
                q1, q3 = CLIP_LIMITS[col]
                clipped_features[col] = max(q1, min(q3, val))
            X_raw = np.array([[clipped_features[col] for col in FEATURE_COLS]])
            prediction = int(xgb_model.predict(X_raw)[0])
            label_name = FAULT_LABELS.get(prediction, 'Unknown')
            
        return jsonify({
            'success': True,
            'telemetry': {
                'vdc': vdc1,
                'idc': idc1,
                'irr': irr_val,
                'pvt': pvt_val,
                'pdc': pdc1,
                'status_code': prediction,
                'status_label': label_name
            }
        })
    else:
        return jsonify({'success': False, 'error': 'Invalid fault ID'}), 400

@app.route('/')
def home():
    return "VoltifyAI Solar Fault Detection API (XGBoost Edition) is Running."

if __name__ == '__main__':
    app.run(debug=True, port=5000)
