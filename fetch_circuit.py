import json
import redis
import pandas as pd
import os


def get_exchange_instrument_id(description):
    """
    Filter options_instruments.csv by description and return ExchangeInstrumentID.
    
    Args:
        description (str): The description to match in the Description column
        
    Returns:
        int or None: The ExchangeInstrumentID if found, None otherwise
    """
    try:
        csv_path = os.path.join(os.path.dirname(__file__), 'instruments_data', 'options_instruments.csv')
        
        if not os.path.exists(csv_path):
            print(f"CSV file not found at: {csv_path}")
            return None
        
        df = pd.read_csv(csv_path)
        
        # Filter by Description column
        filtered = df[df['Description'] == description]
        
        if filtered.empty:
            print(f"No instrument found with description: {description}")
            return None
        
        # Return the first ExchangeInstrumentID found
        return int(filtered.iloc[0]['ExchangeInstrumentID'])
    
    except Exception as e:
        print(f"Error in get_exchange_instrument_id: {e}")
        return None

def get_circuit_limits(instrument_id, host="DESKTOP-CLI5HO6", port=6379, db=1):
    """
    Fetch circuit limits (UC and LC) for a given instrument ID from Redis.
    
    Args:
        instrument_id (int): The ExchangeInstrumentID
        host (str): Redis host (default: DESKTOP-CLI5HO6)
        port (int): Redis port (default: 6379)
        db (int): Redis DB index (default: 1)
        
    Returns:
        dict: Dictionary with 'UC' and 'LC' keys, or None if not found
    """
    try:
        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True,
        )
        client.ping()
        
        key = f"cache:CIRCUIT_{instrument_id}"
        raw_value = client.get(key)
        
        if raw_value is None:
            print(f"No circuit data found for instrument ID: {instrument_id}")
            return None
        
        try:
            data = json.loads(raw_value)
            result = {
                'ts': data.get('ts'),
                'UC': data.get('UC'),
                'LC': data.get('LC')
            }
            return result
        except json.JSONDecodeError:
            print(f"Error parsing circuit data for instrument ID: {instrument_id}")
            return None
            
    except Exception as e:
        print(f"Error in get_circuit_limits: {e}")
        return None

#test purpose
# if __name__ == "__main__":
#     # Example: Get circuit limits for an instrument
#     description = "NIFTY26APR23650PE"
    
#     # Step 1: Get the ExchangeInstrumentID from description
#     instrument_id = get_exchange_instrument_id(description)
    
#     if instrument_id is not None:
#         print(f"Description: {description}")
#         print(f"ExchangeInstrumentID: {instrument_id}")
        
#         # Step 2: Get circuit limits (UC and LC)
#         limits = get_circuit_limits(instrument_id)
        
#         if limits:
#             print(f"Timestamp: {limits['ts']}")
#             print(f"Upper Circuit (UC): {limits['UC']}")
#             print(f"Lower Circuit (LC): {limits['LC']}")
#         else:
#             print("Could not fetch circuit limits")

