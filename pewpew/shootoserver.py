from collections import defaultdict
import datetime
import socket
import random
import pygame
import datetime
import pygame.locals
import pygame.image
import pygame.time
import numpy as np

import signal
from utils import *


server_shutdown = False
def server_shutdown_handler(sig, frame):
    global server_shutdown
    server_shutdown = True

class ShootoServer():
    def __init__(self, address=None, args=None):
        # socket and shit.
        self.connected_clients = []
        self.missing_connection_acks = []
        self.recently_disconnected = []

        self.players = {}
        self.event_queue = []
        self.meta_queue = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if address is not None:
            hostname, port = address.split(':')
            self.socket.bind((hostname, int(port)))
        else:
            self.socket.bind(('localhost', PORT))

        self.servertime = 0
        self.socket.setblocking(0)

        self.bullet_hits = defaultdict(list)
        self.pid = 0
        self.cliaddr_to_pid = {}

        self.gmap = GameMap(mapfile='hugemap.png', server=True)  # erk.

        # gamestate 0 is clock not running.
        self.gamestate = 0

        self.settings = {}
        self.settings['cooldown'] = 1
        self.settings['initial_hp'] = 5
        self.settings['round_length'] = args.timelimit if args.timelimit else 60

        self.timeleft = self.settings['round_length']


        #Install the sigint handler 
        signal.signal(signal.SIGINT, server_shutdown_handler)

    def handle_queues(self):
        if len(self.meta_queue) > 0:
            for cliaddr, meta in self.meta_queue:
                if cliaddr not in self.cliaddr_to_pid.keys():
                    self.player_factory(cliaddr,
                                        meta[1],
                                        meta[2],
                                        meta[3]
                                        )
            self.meta_queue = []

        # Now handle the incoming message and its events, 
        #apply the input
        if len(self.event_queue) > 0:
            # print(f"SERVER: evq size: {len(self.event_queue)}")
            for cliaddr, event in self.event_queue:
                pid = self.cliaddr_to_pid[cliaddr]

                if self.players[pid].net_state.cooldown == 0:
                    self.players[pid].react(
                        event[2], event[3], event[6], event[8], self.gmap)  # react to events

                self.players[pid].net_state.last_applied_event_id = event[7]

            self.event_queue = []

    # check if the bullets of pid hit pid2
    def player_collision(self, pid, pid2):
        # check for collisions against other clients.
        # no self collissions please
        if pid != pid2:
            # check all of pid's bullets for collision with pid2 :(
            bullets_to_remove = []
            for ib, bullet in enumerate(self.players[pid].net_state.bullets):
                if bullet.rect.colliderect(self.players[pid2].net_state.rect):
                    # not your own bullet
                    if not (ib, pid2) in self.bullet_hits[pid]:
                        self.bullet_hits[pid].append((ib, pid2))
                        self.players[pid2].net_state.hitters.append([0.5, pid])  # eh?
                        # only hit if not cooled down
                        if self.players[pid2].net_state.cooldown == 0:
                            self.players[pid2].net_state.health = max(
                                self.players[pid2].net_state.health - 1, 0)
                        bullets_to_remove.append(bullet)

                        # did we die? if so, set a new spawnpoint, but don't move the
                        # player until a cooldown.
                        if self.players[pid2].net_state.health == 0:
                            self.players[pid2].net_state.status = PlayerState.dead
                            self.players[pid].net_state.score += 1.0
                            print(self.players[pid2], " died!")
                            sp = random.randrange(
                                0, len(self.gmap.spawnpoints))
                            # self.players[pid2].rect.x = self.gmap.spawnpoints[sp][0]
                            # self.players[pid2].rect.y = self.gmap.spawnpoints[sp][1]
                            # print("new position: ", self.gmap.spawnpoints[sp])
                            self.players[pid2].net_state.cooldown = self.settings['cooldown']
                            self.players[pid2].net_state.health = self.settings['initial_hp']

            # this removes the bullets shot that hit something.
            self.players[pid].net_state.bullets = [x for x in self.players[pid].net_state.bullets if x not in
                                         bullets_to_remove]

    def server_main(self):
        print("starting server")
        # start a socket, listening for incoming packets.
        # keep a game loop that updates the clients with
        # a gamestate (i.e. the position and velocity of all players)
        # every 100ms or so.
        clock = pygame.time.Clock()

        countdown = 3.0

        time_last_update = datetime.datetime.now()

        #need a handler for the server shutdown, really.
        while(not server_shutdown):
            # dont tick time if game hasn't even started yet.
            self.receive_from_clients()

            # argh her har du føkka det til fordi du tenkte ikkje på at
            # det er serveren som bestemmer gamestate
            if self.gamestate == 0:
                #check if all connected clients are ready
                ready_states = [p.net_state.ready for p in self.players.values()]
                if len(ready_states) > 0 and False not in ready_states:
                    self.timeleft = self.settings['round_length']

                    self.gamestate = 1
                    self.update_clients_gamestate(self.gamestate)
                    continue

            if self.gamestate == 2:
                if self.timeleft < 0:
                    for p in self.players.keys():
                        self.players[p].net_state.ready = False
                        self.players[p].net_state.health = self.settings['initial_hp']
                        self.players[p].net_state.score = 0
                        self.gamestate = 0
                        self.update_clients_gamestate(self.gamestate)
                        continue

            if self.gamestate == 1:
                if self.timeleft < 0:
                    self.gamestate = 2
                    self.update_clients_gamestate(self.gamestate)
                    self.timeleft = 2
                    continue

            secs_since_last_update = (datetime.datetime.now() - time_last_update).total_seconds()
            updates_per_second = 30.
            
            if secs_since_last_update > (1/updates_per_second): 
                # handle the queues!
                self.handle_queues()

                if self.gamestate == 0:
                    time_last_update = datetime.datetime.now()
                    continue
                
                # We're running.
                for pid in self.players.keys():
                    self.players[pid].react(None, None, None, secs_since_last_update, self.gmap)

                    self.players[pid].net_state.cooldown = max(
                        0, self.players[pid].net_state.cooldown - secs_since_last_update)

                    for pid2 in self.players.keys():
                        self.player_collision(pid, pid2)

                    # finally, figure out if bullets hit world objects
                    # collision detection.
                    self.players[pid].bullet_collisions(
                        self.gmap, secs_since_last_update)

                time_last_update = datetime.datetime.now()

                self.update_clients()

    def player_factory(self, cliaddr, name, color, magic):
        self.cliaddr_to_pid[cliaddr] = self.pid
        self.players[self.pid] = Player()
        self.players[self.pid].net_state.name = name
        self.players[self.pid].net_state.cliaddr = cliaddr
        self.players[self.pid].net_state.pid = self.pid
        self.players[self.pid].net_state.magic_value = magic

        # do i really need this?
        sp = random.randrange(0, len(self.gmap.spawnpoints))
        self.players[self.pid].net_state.spawnpoint = sp
        self.players[self.pid].net_state.rect.x = self.gmap.spawnpoints[sp][0]
        self.players[self.pid].net_state.rect.y = self.gmap.spawnpoints[sp][1]

        self.connected_clients.append(cliaddr)
        

        print(
            f"SERVER: Created a new player/client: {name} at {cliaddr}, pid {self.pid}")

        self.pid += 1
        return

    def receive_from_clients(self):
        dat, cliaddr = rcv_socket(self.socket)
        # filter on message type here i guess.
        if not dat:
            return
        if dat[0] == "event":
            self.event_queue.append((cliaddr, dat))
            # print("got event!")
        elif dat[0] == "player_meta":
            # check if we have already made a player for this client.
            self.meta_queue.append((cliaddr, dat))
        elif dat[0] == "player_ready":
            print(f"Received player_ready from {cliaddr}")
            pid = self.cliaddr_to_pid[cliaddr]
            self.players[pid].net_state.ready = True
            self.players[pid].net_state.name = dat[1]  # might have update the name
        elif dat[0] == "player_disconnect":
            self.connected_clients.remove(cliaddr)
            pid = self.cliaddr_to_pid[cliaddr]
            self.recently_disconnected.append((cliaddr, pid))
            p = self.players.pop(pid)
            print(f"{p.name} disconnected!")
            print(self.recently_disconnected)

    def update_clients_gamestate(self, new_gamestate):
        to_send = ["game_statechange", new_gamestate]
        for c in self.connected_clients:
            send_socket(self.socket, to_send, c)

    def update_clients(self):
        to_send = ["state", 42,
                    [p.net_state for k,p in self.players.items()]]
        to_remove = []
        for c in self.connected_clients:
            send_socket(self.socket, to_send, c)

            # disconnect logic... ugly shit.
            for d, p in self.recently_disconnected:
                send_socket(self.socket, ["player_disconnect", p], c)
                to_remove.append((d, p))

        for d, p in to_remove:
            self.recently_disconnected.remove((d, p))

        # we have sent the updates, doesn't really matter anymore. we keep score anyway.
        self.bullet_hits = defaultdict(list)

