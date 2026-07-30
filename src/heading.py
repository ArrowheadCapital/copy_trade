import credentials as cre


data = f"{cre.broker.upper()}: {getattr(cre, 'copy_source_id', '')} -> {cre.username if cre.broker.upper() == 'GREEK' else cre.strategy_name}"
