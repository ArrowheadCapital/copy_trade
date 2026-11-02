"""Shared freeze quantities and Redis sources, versioned with the repository.

"""

niftyFreeze = 1800
bnfFreeze = 900
sensexFreeze = 1000
bankex = 900
midcpnifty = 2800
finnifty = 1800

redis_sources = [
    {"name": "DESKTOP-CLI5HO6", "host": "100.103.231.7", "port": 6379, "db": 1},
    {"name": "Data-KAI", "host": "100.68.131.14", "port": 6379, "db": 1},
]
