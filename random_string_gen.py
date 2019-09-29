import random
import sys

def get_rand_string(number_of_characters):
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    rnd = random.SystemRandom()
    out = ""
    for d in range(number_of_characters):
        i = rnd.randint(0, sys.maxsize)
        i = i % len(chars)
        out = out + chars[i:i+1]
    return out

if __name__ == '__main__':
    print (get_rand_string(6))