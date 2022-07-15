from collections import defaultdict
import argparse
import pygame
from collections import deque
import pygame.locals
import pygame.image
import pygame.time
from pygame import Rect
import numpy as np
from shootoserver import ShootoServer
from client import Client
from utils import *

import sys
from PIL import Image


def signal_handler(sig, frame):
    global game_over
    game_over = True

def main_server(args):
    server = ShootoServer(args.server, args)
    server.server_main()
    quit()


if __name__ == '__main__':

    global game_over  # :(
    game_over = False


    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--server",  action="store",
                        help="Start the server at given ip addr interface")
    parser.add_argument("-t", "--timelimit", action="store")
    parser.add_argument("-c", "--connect",  action="store",
                        help="Start the server")

    args = parser.parse_args()

    if args.server:
        main_server(args)
        sys.exit(0)

    client = Client()
    client.args = args
    client.start_game()

    # we out
    print("Someone killd the game. See ya")
    # let's try to disconnect nicely. who cares if we can't.
    send_socket(client.client_socket, [
                "player_disconnect", client.player.name, client.player.pid], client.server_addr)
    pygame.quit()
