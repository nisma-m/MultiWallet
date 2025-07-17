def get_conversion_rate(from_currency, to_currency):
    
    rates = {
        ('INR', 'USD'): 0.012,
        ('USD', 'INR'): 83.0,
        ('INR', 'BTC'): 0.0000003,
        ('BTC', 'INR'): 3300000,
    }
    return rates.get((from_currency, to_currency), 1)  # default: 1 if same currency
