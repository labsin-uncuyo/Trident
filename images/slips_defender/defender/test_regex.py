import re
alert = """Src IP 8.8.8.8. Detected A DNS TXT answer with high entropy. query: domain.com answer: "TXT 255 URGENT: Operation Nightfall compromised. Y TXT 255 0c5emRHZHlaWE1nZDJGeklHRjBkR0ZqYTJWa0xDQnliM1" entropy: 5.63"""
matches = re.findall(r'"([^"]+)"', alert)
longest = max(matches, key=len) if matches else ""
print(f"Longest quoted string: {longest}")
