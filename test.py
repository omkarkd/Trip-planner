# from tools.tavily_tool import tavily_search

# res = tavily_search("Best travel destinations in Europe")
# print(res)


from tools.flight_tool import search_flights

res = search_flights("Plan a 7 days lhr trip to india")
print(res)





# Set your API key before making the request
# import requests
# import os
# from dotenv import load_dotenv
# load_dotenv()

# API_KEY = os.getenv("FLIGHT_API_KEY")

# resp = requests.get('https://api.flightapi.io/onewaytrip/{API_KEY}/HEL/OUL/2026-11-25/1/0/0/Economy/USD'.format(API_KEY=API_KEY))
# print (resp.json())
