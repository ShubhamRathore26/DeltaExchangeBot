import schedule
import telepot
import telebot
from delta_rest_client import DeltaRestClient, OrderType, TimeInForce
import json
import math
import time, os
import requests
import urllib3
from threading import Thread


proxy_url = "http://proxy.server:3128"
telepot.api._pools = {
    'default': urllib3.ProxyManager(proxy_url=proxy_url, num_pools=3, maxsize=10, retries=False, timeout=30),
}
telepot.api._onetime_pool_spec = (urllib3.ProxyManager, dict(proxy_url=proxy_url, num_pools=1, maxsize=1, retries=False, timeout=30))

os.environ['TZ'] = 'Asia/Kolkata'
time.tzset()


config = open('config.json')
config = json.load(config)
tries = 5



def fetch_id():
    url = 'https://api.delta.exchange/products'
    response = requests.get(url).json()
    json_file = open('instruments.json', 'w')
    json.dump(response, json_file)
    telegram_bot('Updated Instrument IDs.')


def get_id(symbol):
    json_file = json.loads(open('instruments.json', 'r').read())
    for i in json_file:
        if i['symbol'] == symbol:
            return i['id']

def deltaLogin():
    deltaClient = DeltaRestClient(
        base_url=config['delta_base_url'],
        api_key=config['delta_api_key'],
        api_secret=config['delta_api_secret']
    )
    return deltaClient


def message_bot():
    API_KEY = config["telegram_api_key"]
    bot = telebot.TeleBot(API_KEY)
    telegram_bot("TeleBot Started.")
    @bot.message_handler(commands=['isrunning'])
    def isrunning(message):
        bot.reply_to(message, 'Bot is Running.')

    @bot.message_handler(commands=['avlbal'])
    def greet(message):
        bot.reply_to(message, usdt_balance())

    @bot.message_handler(commands=['btcltp'])
    def btcltp(message):
        bot.reply_to(message, get_ltp("BTCUSDT"))

    try:
        bot.polling()
    except:
        telegram_bot("Bot Messenger Has Stopped \nRetrying")
        message_bot()




def telegram_bot(bot_message):
    bot_message = str(bot_message)
    print(bot_message)
    token = config["telegram_api_key"]
    receiver_id = config["telegram_chat_id"]
    bot = telepot.Bot(token)
    return bot.sendMessage(receiver_id, bot_message)


def time_teller():
    current_time = time.strftime("%Y-%m-%d  %H:%M", time.localtime())
    telegram_bot(f'Current Time: {current_time}')
    return current_time


telegram_bot("------------------------------------")
current_time = time_teller()
telegram_bot(f'\nAlgo Bot Started at {current_time} \n')


delta_client = deltaLogin()


def place_order(productId, size, price, side='sell', order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC):
    order_response = delta_client.place_order(
        product_id=productId,
        size=size,
        side=side,
        limit_price=price,
        order_type=order_type,
        time_in_force=time_in_force)
    return order_response


def cancel_order(productId, orderId):
    order_response = delta_client.cancel_order(product_id=productId, order_id=orderId)
    return order_response


def get_ltp(symbol):
    response = delta_client.get_ticker(symbol)['spot_price']
    return response


def usdt_balance():
    balance = delta_client.get_balances(asset_id=5)['available_balance']
    return balance


def orderbook(productId):
    tries = 5
    while tries > 0:
        try:
            time.sleep(1)
            orderbook_bid = delta_client.get_l2_orderbook(productId)['buy'][0]['price']
            orderbook_ask = delta_client.get_l2_orderbook(productId)['sell'][0]['price']
            return orderbook_bid, orderbook_ask
            break
        except Exception as e:
            telegram_bot(f"Error Occurred in Orderbook: {e}")
            tries -= 1


def deltabot():
    # Strike Selection
    ltp = float(get_ltp('BTCUSDT'))
    telegram_bot(f'BTC SPOT Price: {ltp}')
    val = ltp
    val2 = math.fmod(val, 1000)
    x = val - val2
    ce_strike = "{}".format("{:.0f}".format(x + 2000))
    telegram_bot(f'Identified OTM Strike to sell: {ce_strike}')
    # Fetch Symbol Token
    current_date = time.strftime("%d%m%y", time.localtime())
    symbol = f'C-BTC-{ce_strike}-{current_date}'
    product_id = get_id(symbol)
    if product_id is None:
        telegram_bot('Token not Found')
        telegram_bot('Trying Again with other Symbol.')
        ce_strike = int(ce_strike) - 1000
        symbol = f'C-BTC-{ce_strike}-{current_date}'
        product_id = get_id(symbol)
        if product_id is None:
            telegram_bot('Trying 2nd symbol')
            pe_strike = int(ce_strike)-4000
            symbol = f'P-BTC-{pe_strike}-{current_date}'
            product_id = get_id(symbol)
    telegram_bot(f'{symbol}, {product_id}')
    # OrderBook
    orderbook_bid = orderbook(product_id)[0]
    orderbook_ask = orderbook(product_id)[1]
    telegram_bot(f"Bid: {orderbook_bid} Ask: {orderbook_ask}")
    # Available Balance
    balance = delta_client.get_balances(asset_id=5)['available_balance']
    telegram_bot(f"Available Balance: {balance}")
    # Quantity
    cont = int(float(balance) / (ltp / 100000))
    telegram_bot(f"Quantity: {cont}")
    # Set Leverage
    leverage = delta_client.set_leverage(product_id=product_id, leverage='100')
    telegram_bot(f"Leverage changed to {leverage['leverage']}x.")
    tries = 5
    # Order Placement
    if cont > 0 and float(balance) > 0.3:
        while tries > 0:
            try:
                orig_ord = place_order(product_id, size=cont, price=orderbook_bid)
                telegram_bot(f"\nOrder Submitted \n"
                      f"{orig_ord['side']} {orig_ord['size']} Contracts of {orig_ord['product_symbol']} at {orig_ord['limit_price']}")
                break
            except Exception as e:
                telegram_bot(f"Exception Occurred: {e}")
                cont -= 1
                telegram_bot(f'Trying Again with {cont} Quantity.')
                tries -= 1
        telegram_bot('\nStrategy Executed.')
    else:
        telegram_bot("No Balance!")


def live_orders():
    open_orders = delta_client.get_live_orders()
    if open_orders:
        telegram_bot("------------------------------------")
        telegram_bot('Found Existing Orders \n Cancelling Orders...')
        for orders in open_orders:
            cancelled = cancel_order(productId=orders['product_id'], orderId=orders['id'])
            telegram_bot(f"Cancelled {cancelled['product_symbol']}, Quantity: {cancelled['unfilled_size']}")
        telegram_bot('Cancelled Existing Orders. \n')
        time.sleep(1)
        telegram_bot('Started Strategy Execution. \n')
        deltabot()
    else:
        telegram_bot("------------------------------------")
        telegram_bot('Started Strategy Execution. \n')
        deltabot()


def sch_stry():
    schedule.every(120).minutes.do(usdt_balance)
    schedule.every(120).minutes.do(time_teller)
    schedule.every().day.at('17:10:00').do(fetch_id)
    schedule.every().day.at('17:25:00').do(live_orders)
    schedule.every().day.at('18:00:00').do(fetch_id)
    # schedule.every().day.at('19:31:00').do(exit)

    while 1:
        schedule.run_pending()
        time.sleep(1)


Thread(target=sch_stry).start()
Thread(target=message_bot).start()

