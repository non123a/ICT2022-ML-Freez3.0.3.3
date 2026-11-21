import MetaTrader5 as mt5

mt5.initialize()

symbol = "XAUUSD"
info = mt5.symbol_info(symbol)

print("Contract size:", info.trade_contract_size)
print("Tick size:", info.trade_tick_size)
print("Tick value:", info.trade_tick_value)
print("Profit tick value:", info.trade_tick_value_profit)
print("Loss tick value:", info.trade_tick_value_loss)
print("Volume min:", info.volume_min)
print("Volume max:", info.volume_max)
print("Volume step:", info.volume_step)

entry = 3898.61
sl = 3884.51591

loss = mt5.order_calc_profit(
    mt5.ORDER_TYPE_BUY,
    symbol,
    1.0,
    entry,
    sl
)

print("Actual estimated loss for 1 lot:", loss)

mt5.shutdown()