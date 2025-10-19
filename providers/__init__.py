from .defillama import DefiLlamaProvider

# Подключаемые по желанию CEX-провайдеры (заготовки):
try:
    from .binance import BinanceEarnProvider  # noqa: F401
except Exception:
    BinanceEarnProvider = None  # необязательный

PROVIDERS = {
    "defillama": DefiLlamaProvider,
    # "binance": BinanceEarnProvider,  # раскомментируйте после заполнения ключей и проверки
}
