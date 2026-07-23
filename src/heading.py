import credentials as cre


data = f"{cre.broker} {cre.username if cre.broker.upper() == 'GREEK' else cre.strategy_name}"
