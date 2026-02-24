import requests
import time
from fake_useragent import UserAgent

url = "https://www.nykaa.com/brands/dot-key/c/7675?root=search,brand_menu,brand_list,Dot%20&%20Key&searchType=history&suggestionType=brand&ssp=1&searchItem=Dot%20&%20Key&sourcepage=searchSuggestions&searchKeyword=undefined&searchRedirect=1&"

session = requests.Session()

headers = {
    'User-Agent': UserAgent().random,
    'Accept - Language': 'en - US, en;q = 0.9',
    'Accept - Encoding': 'gzip, deflate, br',
    'Connection': 'keep - alive',
    'Referer': 'https://www.nykaa.com/brands/dot-key/c/7675?root=search,brand_menu,brand_list,Dot%20&%20Key&searchType=history&suggestionType=brand&ssp=1&searchItem=Dot%20&%20Key&sourcepage=searchSuggestions&searchKeyword=undefined&searchRedirect=1&',
}

proxies = {
    'http': 'http://<IP_ADDRESS>:8080',
    'https': 'http://<IP_ADDRESS>:8080',
}

time.sleep(2)
r = session.get(url, proxies = proxies, headers=headers)

with open('dot1.html', 'w', encoding='utf-8') as f:
    f.write(r.text)
