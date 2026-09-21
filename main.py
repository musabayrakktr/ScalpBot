import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)


@app.route('/')
def home():
  return jsonify({"status": "live"}), 200


@app.route('/health', methods=['GET'])
def health():
  return "OK", 200


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")


def telegram_gonder(mesaj):
  if not TELEGRAM_TOKEN or not CHAT_ID:
    print('Token/ChatID eksik')
    return
  url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
  payload = {'chat_id': CHAT_ID, 'text': mesaj, 'parse_mode': 'Markdown'}
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f'Mesaj hatası: {e}')


if __name__ == '__main__':
  # İlk açılışta ayağa kalktığını haber versin
  telegram_gonder('💀 *İskelet Bot Ayakta!*')
  port = int(os.environ.get('PORT', 10000))
  app.run(host='0.0.0.0', port=port)
