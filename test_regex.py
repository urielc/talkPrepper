#!/usr/bin/env python3
import re

urls = [
    'https://www.churchofjesuschrist.org/study/general-conference/20102019?lang=eng',
    'https://www.churchofjesuschrist.org/study/general-conference/2025/10?lang=eng'
]

for url in urls:
    result = re.search(r'/\d{8}(?:\?|$)', url)
    print(f'{url}: {"Decade" if result else "Individual"}')


