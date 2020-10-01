import errno
import copy
import os
import argparse
import random
import pygame
import pygame_menu
import select
import datetime
from collections import deque
import math
import pygame.locals
import pygame.image
from pygame import Rect
import glob
import itertools
import numpy as np
#from pytmx.util_pygame import load_pygame
#import pyscroll
#from opensimplex import OpenSimplex

import signal
import sys
import enum
from PIL import Image


class PlayerState(enum.Enum):
    active = 0
    dead = 1

class GameState(enum.Enum):
    lobby = 0
    running = 1

class GameMap():
    def __init__(self, mapfile=None, size=(2000,1000), server=False):
        self.size = size
        self.pixels = None

        if not mapfile:
            for y in range(size[1]):
                self.genmap.append([0] * size[0])
                for x in range(size[0]):
                    v = gen.noise2d(2*x/size[0], 2*y/size[1])
                    self.genmap[y][x] = 1 if v > 0 else 0

        self.pixels = Image.open(mapfile)
        self.size = self.pixels.size
        self.pixels = np.swapaxes(np.asarray(self.pixels), 0, 1)
        if not server:
            self.map = pygame.image.load(mapfile).convert()#.convert_alpha()

        self.current_visible_surface = None

        self.tile_width = 1
        self.tile_height = 1

        self.spawnpoints = [[0,0],
                            [self.size[0]-16, self.size[1] - 1000],
                            [self.size[0]/2, self.size[1]/2]]

    def blit_visible_surface(self, camera_pos, viewport, zoom=1.0):
        #the map is represented in genmap[y][x].
        #the camera moves in pixel-land, but we are interested in
        #in figuring out which map tiles to draw.

        #camera is center, so we draw each side. remember we go top->bottom, left-right.
        visible_top = camera_pos[1] - viewport.get_height()/2.
        #600 - 1024/2 = 600 - 512 = 88.
        visible_left = camera_pos[0] - viewport.get_width()/2.

        #view_rect is in tiles.
        v_left = max(0, min(visible_left, self.size[0]-viewport.get_width()))
        v_top = max(0, min(visible_top, self.size[1]-viewport.get_height()))

        v_width = min(viewport.get_width(), self.size[0])
        v_height = min(viewport.get_height(), self.size[1])

        #view rect is in global map px coordinates. it is the 'visible rect'.
        view_rect = pygame.Rect(v_left, v_top, v_width, v_height)

        self.current_visible_surface = self.map.subsurface(view_rect)

        viewport.blit(self.current_visible_surface, (0, 0))
        return (view_rect)

#just a datastructure
class Bullet():
    def __init__(self, pos = None, velocity = None):
        self.velocity = velocity
        self.rect = pygame.Rect(pos, (8, 8))
        self.color = pygame.Color(255, 0, 0)
        self.type = 0
        #self.img = pygame.Surface((8,8))
        #self.img.fill(self.color)


class Player(pygame.sprite.Sprite):
    def __init__(self, pos=(0, 0), frames=None, color=pygame.Color(255, 0, 0), client=False, hp=5):
        super().__init__()

        self.movespeed = 800
        self.jumpspeed = 1500
        self.gravity = 1000

        self.velocity = [0., 0.]
        self.grounded = False
        self.facing_left = False

        self.pid = -1

        self.client = client
        self.updates_without_events = 0
        self.cliaddr = None
        self.magic_value = None

        self.color = color
        self.img = pygame.Surface((16, 16))
        self.img.fill(self.color)

        self.hitters = []
        self.hit_img = pygame.Surface((16, 16))
        self.hit_img.fill((255, 255, 255))


        self.death_anim = Animation(fps=30)
        self.death_anim.load_frames_sheet((8,8), 'particlefx_12.png', scale=3.0)


        self.rect = pygame.Rect(pos, (16, 16))
        self.posx = pos[0]
        self.posy = pos[1]

        #these are things that are fired and needs updating when time ticks.
        self.bullets = []
        self.name = "Jumbo"
        self.score = 0
        self.ready = False
        self.health = hp

        self.holding_up = False
        self.holding_down = False

        self.spawnpoint = 0
        self.cooldown = 0
        self.status = PlayerState.active

    def update_color(self, col):
        self.color = col
        self.img.fill(self.color)

    def react(self, event_type, event_key, keystate):
        print(f"EVENT KEY {event_key}")
        if event_type == pygame.KEYDOWN:
            if event_key == pygame.K_a:
                self.facing_left = True
                self.velocity[0] = -self.movespeed
            if event_key == pygame.K_d:
                self.facing_left = False
                self.velocity[0] = self.movespeed
                print(f"GOING RIGHT, {self.velocity[0]}")
            if event_key == pygame.K_j:
                if self.grounded:
                    self.velocity[1] = -self.movespeed
            if event_key == pygame.K_w:
                self.holding_up = True
            if event_key == pygame.K_s:
                self.holding_down = True

            if event_key == pygame.K_k:
                #fire weapon
                vel = []
                #holding up
                if self.holding_up:
                    vel = [0, -self.jumpspeed]
                #down
                elif self.holding_down:
                    vel = [0, self.jumpspeed]
                else:
                    if self.facing_left:
                        vel = [-self.jumpspeed, 0]
                    else:
                        vel = [self.jumpspeed, 0]
                self.bullets.append(Bullet(pos = self.rect.center, velocity=vel))
                #print(f'added bullet at {self.rect.center}, speed {vel}')


        if event_type == pygame.KEYUP:
            #pressed keys
            if event_key == pygame.K_a and self.velocity[0] <= 0:
                if keystate[pygame.K_d]:
                    self.facing_left = False
                    self.velocity[0] = self.movespeed
                else:
                    self.velocity[0] = 0
            if event_key == pygame.K_d and self.velocity[0] > 0:
                if keystate[pygame.K_a]:
                    self.facing_left = True
                    self.velocity[0] = -self.movespeed
                else:
                    self.velocity[0] = 0
            if event_key == pygame.K_j and self.velocity[0] < 0:
                self.velocity[1] = 0
            if event_key == pygame.K_w:
                self.holding_up = False
            if event_key == pygame.K_s:
                self.holding_down = False



    #remember mappy needs to be a pixel array
    #update the state of the player based on inputs and other external factors
    def update(self, mappy, dt):
        self.grounded = False

        delta_distance_x = self.velocity[0] * dt
        self.posx += delta_distance_x
        self.rect.x = int(max(0, min(mappy.size[0]-16, self.posx)))

        #px = pygame.PixelArray(mappy.map)
        px = mappy.pixels

        raylen = 10# int(abs(delta_distance_y)) + 1

        #collision_value = mappy.map.map_rgb(255,0,0)  #what?
        collision_value = [255,0,0]

        #bottom collision, iterate all pixels and check for match.
        if self.velocity[1] >= 0: #we are falling, positive is down.
            for rpixl in range(self.rect.bottom, min(mappy.size[1], self.rect.bottom + raylen)):
                if (px[self.rect.centerx][rpixl] == collision_value).all():
                    self.rect.bottom = rpixl  #set the y position to the grounded coordinate
                    #self.posy = self.rect.bottom
                    self.velocity[1] = 0
                    self.grounded = True   
                    break
        
        delta_distance_y = 0.0
        #if we are not grounded, 
        if not self.grounded: 
            self.velocity[1] += self.gravity * dt   #gravity, but why is this fucked?
            delta_distance_y = self.velocity[1] * dt
            self.posy += delta_distance_y
            self.rect.y = int(max(0, min(mappy.size[1]-16, self.posy)))

        print(f"updated: {self.velocity[0]}, dt {dt}, delta {delta_distance_x} newpos {self.posx} newrect {self.rect.x}")
        print(f"updated: {self.velocity[1]}, dt {dt}, delta {delta_distance_y} newpos {self.posy} newrect {self.rect.y}")

        #update bullets
        for b in self.bullets:
            b.rect.x += dt * b.velocity[0]
            b.rect.y += dt * b.velocity[1]

        to_remove = []
        for idx, (timeleft, hitter) in enumerate(self.hitters):
            if timeleft <= 0.0:
                to_remove.append(idx)
            else:
                self.hitters[idx][0] = max(0.0, timeleft - dt)
        for idx in set(to_remove):
            self.hitters.pop(idx)

        #if we died 
        if self.status == PlayerState.dead:
            if self.cooldown == 0:
                self.status = PlayerState.active
                sp = random.randrange(0, len(mappy.spawnpoints))
                self.rect.x = mappy.spawnpoints[sp][0]
                self.rect.y = mappy.spawnpoints[sp][1]
                self.posx = self.rectx
                self.posy = self.recty


    def bullet_collisions(self, mappy, dt):
        #px = pygame.PixelArray(mappy.map)
        px = mappy.pixels
        for b in self.bullets:
            if b.rect.right > mappy.size[0]:
                self.bullets.remove(b)
                continue
            if b.rect.left < 0:
                self.bullets.remove(b)
                continue
            if b.rect.top > mappy.size[1]:
                self.bullets.remove(b)
                continue
            if b.rect.bottom < 0:
                self.bullets.remove(b)
                continue

            delta_distance_y = dt * b.velocity[1]
            raylen = int(abs(delta_distance_y)) + 1

            collision_value = [255, 0, 0]
            #bottom collision, iterate all pixels and check for match.
            if b.velocity[1] > 0: #bullets going down
                if self.grounded:
                    self.bullets.remove(b)
                    continue
                for rpixl in range(b.rect.bottom, min(mappy.size[1], b.rect.bottom + raylen)):
                    if (px[b.rect.centerx][rpixl] == collision_value).all():
                        self.bullets.remove(b)
                        break
            #bullets going up
            elif b.velocity[1] < 0:
                #print(b.rect.top - raylen, b.rect.top)
                for rpixl in range(max(0, b.rect.top - raylen), b.rect.top):
                    if (px[b.rect.centerx][rpixl] == collision_value).all():
                        self.bullets.remove(b)
                        break

        #px.close()

        return


import socket
import pickle

from collections import defaultdict


class ShootoServer():
    def __init__(self, address=None):
        #socket and shit.
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
            print("bound socket")
        else:
            self.socket.bind(('localhost', PORT))

        self.servertime = 0
        self.socket.setblocking(0)

        self.bullet_hits = defaultdict(list)
        self.pid = 0
        self.cliaddr_to_pid = {}

        self.gmap = GameMap(mapfile='hugemap.png', server=True) #erk.

        #gamestate 0 is clock not running.
        self.gamestate = 0

        self.settings = {}
        self.settings['cooldown'] = 1
        self.settings['initial_hp'] = 5
        self.settings['round_length'] = args.timelimit if args.timelimit else 60

        self.timeleft = self.settings['round_length']

        self.send_sequence_nr = 0
        self.rec_sequence_nr = {}  #one per pid.

    def handle_queues(self):
        if len(self.meta_queue) > 0:
            for cliaddr, meta in self.meta_queue:
                if cliaddr not in self.cliaddr_to_pid.keys():
                    print("SERVER: Got meta package:", meta)
                    self.player_factory(cliaddr,
                                    meta[1],
                                    meta[2],
                                    meta[3]
                                    )
                pid = self.cliaddr_to_pid[cliaddr]
                self.players[pid].name = meta[1]
                self.players[pid].color = meta[2]

            self.meta_queue = []

        if len(self.event_queue) >  0:
            print(f"SERVER: evq size: {len(self.event_queue)}")
            for cliaddr, event in self.event_queue:
                pid = self.cliaddr_to_pid[cliaddr]
                if event[7] <= self.rec_sequence_nr[pid]:
                    print("SERVER: Warning, packet ouf of sequence!")
                    return

                if self.players[pid].cooldown == 0:
                    self.players[pid].react(event[2], event[3], event[6])  #react to events
                    print("SERVER:", event[2], event[3], event[6])
                    

                self.players[pid].updates_without_events = 0

            self.event_queue = []

    #check if the bullets of pid hit pid2
    def player_collision(self, pid, pid2):
        #check for collisions against other clients.
        #no self collissions please
        if pid != pid2:
            #check all of pid's bullets for collision with pid2 :(
            bullets_to_remove = []
            for ib, bullet in enumerate(self.players[pid].bullets):
                if bullet.rect.colliderect(self.players[pid2].rect):
                    #not your own bullet
                    if not (ib, pid2) in self.bullet_hits[pid]:
                        self.bullet_hits[pid].append((ib, pid2))
                        self.players[pid2].hitters.append([0.5, pid]) #eh?
                        #only hit if not cooled down
                        if self.players[pid2].cooldown == 0:
                            self.players[pid2].health = max(self.players[pid2].health - 1, 0)
                        bullets_to_remove.append(bullet)

                        #did we die? if so, set a new spawnpoint, but don't move the
                        #player until a cooldown.
                        if self.players[pid2].health == 0:
                            self.players[pid2].status = PlayerState.dead
                            self.players[pid].score += 1.0
                            print(self.players[pid2], " died!")
                            sp = random.randrange(0, len(self.gmap.spawnpoints))
                            #self.players[pid2].rect.x = self.gmap.spawnpoints[sp][0]
                            #self.players[pid2].rect.y = self.gmap.spawnpoints[sp][1]
                            #print("new position: ", self.gmap.spawnpoints[sp])
                            self.players[pid2].cooldown = self.settings['cooldown']
                            self.players[pid2].health = self.settings['initial_hp']


            #this removes the bullets shot that hit something.
            self.players[pid].bullets = [x for x in self.players[pid].bullets if x not in
                                        bullets_to_remove]



    def server_main(self):
        print("starting server")
        global game_over
        #start a socket, listening for incoming packets.
        #keep a game loop that updates the clients with
        #a gamestate (i.e. the position and velocity of all players)
        #every 100ms or so.
        clock = pygame.time.Clock()

        countdown = 3.0

        #t = datetime.datetime.now()
        #dt = 0
        time_last_update = datetime.datetime.now()
        time_last_update_2 = datetime.datetime.now()

        while(not game_over):
            #dont tick time if game hasn't even started yet.
            self.receive_from_clients()

            #argh her har du føkka det til fordi du tenkte ikkje på at
            #det er serveren som bestemmer gamestate
            if self.gamestate == 0:
                ready_states = [p.ready for p in self.players.values()]
                if len(ready_states) > 0 and False not in ready_states:
                    self.timeleft = self.settings['round_length']

                    self.gamestate = 1

            if self.gamestate == 1:
                if self.timeleft < 0:
                    self.gamestate = 2
                    self.timeleft = 2

            if self.gamestate == 2:
                if self.timeleft < 0:
                    for p in self.players.keys():
                        self.players[p].ready = False
                        self.players[p].health = self.settings['initial_hp']
                        self.players[p].score = 0
                        self.gamestate = 0

            diff = datetime.datetime.now() - time_last_update
            #20 sort of magic number... means 50 updates per second.
            if diff.total_seconds() * 1000 > 1:
                #handle the queues!
                self.handle_queues()

                if self.gamestate == 0:
                    time_last_update = datetime.datetime.now()
                    continue


                for pid in self.players.keys():
                    self.players[pid].cooldown = max(0, self.players[pid].cooldown - diff.total_seconds())
                    self.players[pid].update(self.gmap, diff.total_seconds()) #collision detection.
                    self.players[pid].updates_without_events += 1

                    for pid2 in self.players.keys():
                        self.player_collision(pid, pid2)

                    #finally, figure out if bullets hit world objects
                    self.players[pid].bullet_collisions(self.gmap, diff.total_seconds()) #collision detection.

                time_last_update = datetime.datetime.now()

            #Update the clients 50 Hz
            diff = datetime.datetime.now() - time_last_update_2
            if diff.total_seconds() * 1000 > 20:
                if self.gamestate == 1 or self.gamestate == 2:
                    self.timeleft -= diff.total_seconds()
                self.update_clients()
                time_last_update_2 = datetime.datetime.now()

            #prune dead users..
            #for pid in self.players.keys():
            #    if self.players[pid].updates_without_events > 10000:
                    #let's remove...
            #        self.connected_clients.remove(self.players[pid].cliaddr)
            #        self.recently_disconnected.append((self.players.cliaddr, pid))
            #        p = self.players.pop(pid)
            #        print(f"SERVER: {p.name} disconnected!")



    def player_factory(self, cliaddr, name, color, magic):
        self.cliaddr_to_pid[cliaddr] = self.pid
        self.players[self.pid] = Player(color=color, hp=self.settings['initial_hp'])
        self.players[self.pid].name = name
        self.players[self.pid].cliaddr = cliaddr
        self.players[self.pid].pid = self.pid
        self.players[self.pid].magic_value = magic

        #do i really need this?
        sp = random.randrange(0, len(self.gmap.spawnpoints))
        self.players[self.pid].spawnpoint = sp
        self.players[self.pid].rect.x = self.gmap.spawnpoints[sp][0]
        self.players[self.pid].rect.y = self.gmap.spawnpoints[sp][1]

        self.connected_clients.append(cliaddr)
        self.rec_sequence_nr[self.pid] = -1   #first packet should have 0 in seqnr
        self.pid += 1
        print(f"SERVER: Created a new player: {name} at {cliaddr}")

        return 

    def receive_from_clients(self):
        dat, cliaddr = rcv_socket(self.socket)
        #filter on message type here i guess.
        if not dat:
            return
        if dat[0] == "event":
            self.event_queue.append((cliaddr, dat))
            #print("got event!")
        elif dat[0] == "player_meta":
            #check if we have already made a player for this client.
            self.meta_queue.append((cliaddr, dat))
        elif dat[0] == "player_ready":
            pid = self.cliaddr_to_pid[cliaddr]
            self.players[pid].ready = True
            self.players[pid].name = dat[1]  #might have update the name
        elif dat[0] == "player_disconnect":
            self.connected_clients.remove(cliaddr)
            pid = self.cliaddr_to_pid[cliaddr]
            self.recently_disconnected.append((cliaddr, pid))
            p = self.players.pop(pid)
            print(f"{p.name} disconnected!")
            print(self.recently_disconnected)


    def update_clients(self):
        state = ["state", self.send_sequence_nr,
                            [(p.pid,
                            p.name,
                            p.rect.x, p.rect.y,
                            p.velocity[0], p.velocity[1],
                            p.bullets,
                            p.score,
                            p.hitters,
                            p.color,
                            p.magic_value,
                            p.ready,
                            self.gamestate,
                            p.health,
                            self.timeleft,
                            p.cooldown,
                            p.status,
                            p.posx,
                            p.posy) for k, p in
            self.players.items()]]
        to_remove = []
        for c in self.connected_clients:
            send_socket(self.socket, state, c)

            #disconnect logic... ugly shit.
            for d, p in self.recently_disconnected:
                send_socket(self.socket, ["player_disconnect", p], c)
                to_remove.append((d,p))

        for d,p in to_remove:
            self.recently_disconnected.remove((d,p))

        #we have sent the updates, doesn't really matter anymore. we keep score anyway.
        self.bullet_hits = defaultdict(list)
        self.send_sequence_nr += 1


def main_server(args):
    server = ShootoServer(args.server)
    server.server_main()
    quit()


def send_socket(socket, msg, to):
    msg = pickle.dumps(msg)
    try:
        sent = socket.sendto(msg, to)
    except OSError as e:
        print(e)
        return socket

def rcv_socket(socket):
    MSGLEN = 2048
    chunks = []
    bytes_rcv = 0
    #while bytes_rcv < MSGLEN: #header
    try:
        chunk, server = socket.recvfrom(MSGLEN)
        chunks.append(chunk)
    except OSError as e:
        if e.errno == errno.EWOULDBLOCK:
            return None, None
        if chunk == b'':
            print("WARNING: SOCKET BROKEN. ASSUMING ALL IS SHIT AND REMOVING THIS SOCKET.")

    msg = pickle.loads(b''.join(chunks))
    #print("received message ", msg)
    return msg, server


class TextInputBox():
    def __init__(self, leadtext="", position = (0,0), font_color=(0,0,0)):
        self.font = pygame.font.Font('inconsolata.ttf', 16)
        self.font_color = font_color
        self.leadtext = leadtext
        self.entered_text = ""
        self.position = position
        self.has_focus = True

    def add_char(self, char):
        self.entered_text += char

    def del_char(self):
        self.entered_text = self.entered_text[:-1]

    def render_text(self, target_surface):
        letter_render = self.font.render(self.leadtext + self.entered_text, True, self.font_color)
        target_surface.blit(letter_render, self.position)

"""
class SelectBox():
    def __init__(self, options=None, font='inconsolata.ttf', fontsize=32, color=(255,0,0)):
        self.selected_option = 0
        self.options = options
        self.color = color
        self.full_surface = None
        self.font = pygame.font.Font(font, fontsize)

    def draw_options(self):
        if self.options is None:
            return pygame.Surface((0,0))

        offset = 0.0
        for text in self.options:
            tsurf = self.font.render(text, True, self.color)
            offset += tsurf.get_rect().top
"""

class TextMessage():
    def __init__(self, text, position, duration, fontface='inconsolata.ttf', fontsize=32):
        green = (0, 255, 0)
        self.color = pygame.Color('black')
        self.font = pygame.font.Font(fontface, fontsize)
        self.rtext = self.font.render(text, True, self.color)

        self.textrect = self.rtext.get_rect()
        self.textrect.topleft = position
        self.timeleft = duration

    def update_text(self, new_text):
        self.rtext = self.font.render(new_text, True, self.color)

    def get_surface(self, dt=0):
        if (self.timeleft > 0) or (self.timeleft == 0):
            self.timeleft -= dt
            return self.rtext
        else:
            print("timeleft", self.timeleft)
            return None

class MultilineTextBox():
    def __init__(self, lines=[], color = pygame.Color('black'), font = 'inconsolata.ttf', fontsize = 20, bgcolor = (50, 500, 100, 255)):
        self.lines = lines
        self.textsurface = pygame.Surface((1, 1))
        self.fontcolor = color
        self.fontsize = fontsize
        self.bgcolor = bgcolor
        self.font = pygame.font.Font(font, fontsize)

    def update(self, lines):
        self.lines = lines
        self.update_surface()

    def get_surface(self):
        return self.textsurface

    def update_surface(self):
        #re-render and return a new surface.
        row_surf = []
        for row in self.lines:
            row_surf.append(self.font.render(row, True, self.fontcolor))

        max_width = 0
        max_height = 0
        if len(self.lines) > 0:
            max_row = max(row_surf, key = lambda x: x.get_width())
            max_width = max_row.get_width()
            max_height = max_row.get_height()
        else:
            return self.textsurface

        self.textsurface = pygame.Surface((max_width, max_height * len(self.lines)),
                                            pygame.SRCALPHA)

        print(f"surface made with dims {self.textsurface.get_size()}")
        #fill the surface with black and fully visible alpha channel.
        #blend_mult will multiply pixels and shift 8 right (div by 256)
        self.textsurface.fill(self.bgcolor)
        for rownum, line_surface in enumerate(row_surf):
            self.textsurface.blit(line_surface, (0, max_height * rownum), special_flags = pygame.BLEND_RGBA_MULT)


        return self.textsurface



class ScoreBoard():
    def __init__(self):
        self.players = []
        self.scoresurface = None

    def add_player(self, player):
        self.players.append(player)
        self.update_scoreboard_surface()

    def remove_player(self, player):
        self.players.remove(player)
        self.update_scoreboard_surface()

    def get_scoreboard_surface(self):
        if self.scoresurface == None:
            return pygame.Surface((1,1))
        else:
            return self.scoresurface

    def update_scoreboard_surface(self):
        row_height = 22
        row_width = 400

        #just to get the size of the object to be... this is shit and ou know it.
        row = TextMessage("Kills: ",
                              (0,0), 0, fontsize=20)
        surfdims = row.get_surface(0).get_size()

        surfsize = (row_width, surfdims[1] * len(self.players))
        final_surface = pygame.Surface(surfsize, pygame.SRCALPHA)
        final_surface.fill((255,255,255,255))

        rownum = 0
        for p in reversed(sorted(self.players, key=lambda x: x.score)):
            row = TextMessage(p.name + " Kills: " + str(p.score),
                              (0,0), 0, fontsize=20)
            final_surface.blit(row.get_surface(0), (0, surfdims[1] * rownum), special_flags =
                    pygame.BLEND_RGBA_MULT)
            final_surface.fill((0,0,0,0), rect=pygame.Rect(row.get_surface(0).get_width(),
                                                        rownum * surfdims[1],
                                                        row_width - row.get_surface(0).get_width(),
                                                        surfdims[1]),
                                        special_flags = pygame.BLEND_RGBA_MULT
                                    )

            rownum += 1

        self.scoresurface = final_surface

def signal_handler(sig, frame):
    global game_over
    game_over = True


class Client():
    def __init__(self):
        pygame.init()
        self.screeenwidth = 1600
        self.screenheight = 1200
        self.screen = pygame.display.set_mode((self.screeenwidth,self.screenheight))

 
        self.allowed_keys = [pygame.K_a, pygame.K_b, pygame.K_c, pygame.K_d, pygame.K_e, pygame.K_f,
                             pygame.K_g, pygame.K_h, pygame.K_i, pygame.K_j, pygame.K_k, pygame.K_l,
                             pygame.K_m, pygame.K_n, pygame.K_o, pygame.K_p, pygame.K_q, pygame.K_r,
                             pygame.K_s, pygame.K_t, pygame.K_u, pygame.K_v, pygame.K_w, pygame.K_x,
                             pygame.K_y, pygame.K_z]

        self.client_socket = None
        self.server_addr = None
        self.other_players = {}

        self.args = None

        random.seed(datetime.datetime.now())
        col = ( random.randint(0,255),
                random.randint(0,255),
                random.randint(0,255))

        #makes a new player...
        self.player = Player(color = col)
        self.player.name = "Jumbo"
        self.player.rect.x = 600
        self.player.rect.y = 0
        self.player.pid = -1

        self.prev_state_player = Player(color = col)
        self.prev_state_player.name = ""
        self.prev_state_player.rect.x = 600
        self.prev_state_player.rect.y = 0
        self.prev_state_player.pid = -1

        self.scoreboard = ScoreBoard()
        self.scoreboard.add_player(self.player)

        self.health_bar = TextMessage("HP: " + str(self.player.health), (0,0), 0)

        self.gamestate = 0
        self.timeleft = 0.0
        self.timeleft_bar = TextMessage("{:.1f}".format(self.timeleft),
                                        (0,0),
                                        0,
                                        fontsize=20)

        #first state packet is 0 or above.
        self.last_seq_nr = -1
        self.send_seq_nr = 0

    def start_game(self):
        global game_over
        while not game_over:
            if self.gamestate == 0:
                print("Opening!")
                self.opening()
            elif self.gamestate == 1:
                print("Main game starting!")
                self.main_game()
            elif self.gamestate == 2:
                print("Ended!")
                self.ending()
            else:
                print("Weird gamestate oh no")



    def connect_server(self, server_addr=None):
        global game_over

        if self.client_socket is None:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if server_addr is None:
                self.server_addr = ('localhost', PORT)
            else:
                hostname, port = server_addr.split(':')
                self.server_addr = (hostname, int(port))
            self.client_socket.setblocking(0)
            #generate a magic value
            self.player.magic_value = random.randint(0,10000)
            print(f"CLIENT: created socket, my magic number is {self.player.magic_value}")

        #attempt to send the connect packet.
        send_socket(self.client_socket, ["player_meta", self.player.name, self.player.color,
                                    self.player.magic_value], self.server_addr)

    def send_player_ready(self, server_addr=None):
        send_socket(self.client_socket, ["player_ready", self.player.name, self.player.magic_value], self.server_addr)

    #gamestate 2
    def ending(self):
        #render the name input box
        ending_done = False
        bgcolor = (200, 150, 100, 255)
        tb = MultilineTextBox(bgcolor = bgcolor)
        plr_list = []
        old_plr_list = []
        last_update = datetime.datetime.now()
        connected = False
        fps = 60
        clock = pygame.time.Clock()
        send_player_ready = False
        name_locked = False

        while self.gamestate == 2:
            self.screen.fill(bgcolor)
            self.screen.blit(self.scoreboard.get_scoreboard_surface(), (10,10))
            self.receieve_state()
            pygame.display.flip()

            #change gamestate after a while...



    #select map, player name and bot opponents
    #gamestate 0
    def opening(self):
        global game_over
        #render the name input box
        #tib = TextInputBox("Name, then enter: ", (10,10))
        #tib.entered_text = self.player.name
        #_tib = pygame_menu.widgets.TextInput(label="Test", textinput_id='name_input')

        #send_player_ready = False
        print(self.player.name)
        def menu_start_game(self, text):
            self.player.ready = True
            self.send_player_ready(server_addr=self.args.connect)
            #self.gamestate = 1

        def menu_player_change_name(text):
            self.player.name = text

        menu = pygame_menu.Menu(800,800, 'Shooto!')
        menu.add_text_input('Player name: ', default=self.player.name, textinput_id="player_name",
                onchange=menu_player_change_name)
        menu.add_button('Mark ready!', menu_start_game, self, menu.get_widget("player_name").get_value())
        menu.add_label("Players: ", label_id='playerlist')

        #active_box = tib
        opening_done = False
        bgcolor = (150, 150, 200, 255)
        #tb = MultilineTextBox(bgcolor = bgcolor)
        plr_list = []
        old_plr_list = []
        last_update = datetime.datetime.now()
        connected = False
        fps = 60
        clock = pygame.time.Clock()
        name_locked = False

        #this is the lobby state...
        while self.gamestate == 0:
            dt = clock.tick_busy_loop(fps) / 1000.
            self.screen.fill(bgcolor)

            if menu.is_enabled():
                menu.update(pygame.event.get())
                menu.draw(self.screen)

            if (datetime.datetime.now() - last_update).total_seconds() > 0.2:
                self.connect_server(server_addr=self.args.connect)

                last_update = datetime.datetime.now()

            self.receieve_state()   #update the other_players thingy.

            #Now we create a list of all the players, and jankily mark the ready players as ready.
            plr_info = [(plr.name, plr.ready, plr.pid) for plr in self.other_players.values()]
            plr_list = [(p[2], p[0] + " ready!") if p[1] else (p[2], p[0]) for p in plr_info]

            #I AM SORRY ABOUT THIS FUTURE ME, I SUCK AND THIS SORTA WORKS so... i kept it.
            #Add ourselves to the list of players.
            if self.player.pid != -1:
                to_print = self.player.name
                if self.player.ready:
                    to_print = to_print + " ready!"
                plr_list.append((self.player.pid, to_print))

            #nowwww we need to be careful when we update the list of players.
            for pid, name in plr_list:
                if(pid == -1):
                    continue
                label_id = f"lobbylist_{pid}"
                if menu.get_widget(label_id):
                    menu.get_widget(label_id).set_title(name)
                else:
                    menu.add_label(name, label_id=label_id)

            pygame.display.flip()

    #gamestate 1
    def main_game(self):
        global game_over
        gmap = GameMap(mapfile='hugemap.png')
        zoom = 1.0
        fps = 60.
        clock = pygame.time.Clock()

        write_rdy = []
        read_rdy = []

        eventcount = 0

        bullet_img = pygame.Surface((8,8))
        bullet_img.fill(pygame.Color(255,0,100))


        t_last_update = datetime.datetime.now()
        #while not game_over:
        while self.gamestate == 1:
            dt = clock.tick_busy_loop(fps) / 1000.

            client.receieve_state()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    game_over = True
                if event.type == pygame.KEYDOWN or event.type == pygame.KEYUP:
                    _, write_rdy, in_err = select.select([],[client.client_socket],[client.client_socket], 0)
                    keystate = pygame.key.get_pressed()
                    #send event to server
                    if client.client_socket in write_rdy:
                        msg = ["event", eventcount, event.type, event.key, client.player.name, dt,
                                keystate, self.send_seq_nr]
                        send_socket(client.client_socket, msg, client.server_addr)
                        self.send_seq_nr += 1
                    #but also update local player
                    client.player.react(event.type, event.key, keystate)
                    client.player.update(gmap, dt)


                #print(f"Message received: {pickle.loads(b''.join(chunks))}")

            v_rect = gmap.blit_visible_surface((client.player.rect.x, client.player.rect.y), client.screen, zoom)

            #draw the players own bullets...
            blitimg = client.player.img
            for b in client.player.bullets:
                #bullets is in world coords.
                dest_x = max(0, min(b.rect.x - v_rect.left, client.screen.get_width()))
                dest_y = max(0, min(b.rect.y - v_rect.top, client.screen.get_height()))
                client.screen.blit(bullet_img, (dest_x, dest_y))

            #also, were we hit by some bullet?
            #print(player.hitters)
            for timeleft, h in client.player.hitters:
                if timeleft > 0.0:
                    blitimg = client.player.hit_img
                    break #we have been hit.


            if client.player.status == PlayerState.dead:
                death_anim_pos = (client.player.rect.centerx -
                        client.player.death_anim.get_center_offset()[0] - v_rect.left,
                                  client.player.rect.centery -
                                      client.player.death_anim.get_center_offset()[1] - v_rect.top)
                client.screen.blit(client.player.death_anim.next_frame(dt), death_anim_pos)
                if client.player.cooldown == 0:
                    client.player.death_anim.reset()
            else:
                client.screen.blit(blitimg, (client.player.rect.x - v_rect.left, client.player.rect.y - v_rect.top))
                
            #in case we haven't gotten a new update yet, let's predict where the clients are, assuming
            #they kept the velocity we saw last.
            for pid, plr in client.other_players.items():
                if (datetime.datetime.now() - t_last_update).total_seconds() > dt:
                    plr.velocity[1] += 1000. * dt   #is this even correct. i don't know.
                    plr.rect.x += int(plr.velocity[0] * dt)
                    plr.rect.y += int(plr.velocity[1] * dt)

                blitimg = plr.img
                for b in plr.bullets:
                    #bullets is in world coords.
                    dest_x = max(0, min(b.rect.x - v_rect.left, client.screen.get_width()))
                    dest_y = max(0, min(b.rect.y - v_rect.top, client.screen.get_height()))
                    client.screen.blit(bullet_img, (dest_x, dest_y))

                for timeleft, h in plr.hitters:
                    if timeleft > 0.0:
                        blitimg = plr.hit_img
                        break #all we need to know.


                if plr.status == PlayerState.dead:
                    death_anim_pos = (plr.rect.centerx -
                            plr.death_anim.get_center_offset()[0] - v_rect.left,
                                      plr.rect.centery -
                                          plr.death_anim.get_center_offset()[1] - v_rect.top)
                    client.screen.blit(plr.death_anim.next_frame(dt), death_anim_pos)
                    if plr.cooldown == 0:
                        plr.death_anim.reset()
                else:
                    client.screen.blit(blitimg, (plr.rect.x - v_rect.left, plr.rect.y - v_rect.top))
                    

            #draw the hud
            if client.prev_state_player.health != client.player.health:
                client.health_bar.update_text("HP: " + str(client.player.health))

            client.timeleft_bar.update_text("{:.1f}".format(client.timeleft))
            client.screen.blit(client.timeleft_bar.get_surface(), (180, 10))

            hp_srf = client.health_bar.get_surface()
            client.screen.blit(hp_srf, (310, 10))

            client.scoreboard.update_scoreboard_surface()
            client.screen.blit(client.scoreboard.get_scoreboard_surface(), (10,10))

            pygame.display.flip()

        #gamestate changed
        return

    def update_player(self, player, state):
        #don't update our own name because this breaks the opening
        if player != self.player:
            player.name = state[1]

        player.rect.x = state[2]
        player.rect.y = state[3]
        player.velocity = [state[4],state[5]]
        player.bullets = state[6]
        player.score = state[7]
        player.hitters = state[8]
        player.magic_value = state[10]
        player.ready = state[11]
        self.gamestate = state[12]
        player.health = state[13]
        self.timeleft = state[14]
        player.cooldown = state[15]
        player.status = state[16]
        player.posx = state[17]
        player.posy = state[18]

        if state[9] != self.player.color:
            self.player.update_color(state[9])

    #receieve all player states -- this happens only periodically.
    def receieve_state(self):
        if self.client_socket:
            read_rdy, _, in_err = select.select([self.client_socket],[],[self.client_socket], 0)
        else:
            return
        for self.client_socket in read_rdy:
            msg, srv = rcv_socket(self.client_socket)
            if msg[0] == "state":
                t_last_update = datetime.datetime.now()

                #sequence number magic.
                seqnr = int(msg[1])

                if seqnr <= self.last_seq_nr:
                    print(f"Client warning, packet out of sequence ({seqnr}), expected >\
                            {self.last_seq_nr}")
                    return
                
                self.last_seq_nr = seqnr

                #this is already decoded
                for p in msg[2]:
                    pid = p[0]

                    #PIDs are generated on the server, so we don't have one initially.
                    #but we do send a magic value that identifies ourselves so we know which PID is
                    #ours. This is hacky, yes.
                    #usually first connect
                    if self.player.pid == -1:
                        if p[10] == self.player.magic_value:
                            self.player.pid = p[0]
                        else:
                            print(f"CLIENT: Got a pid with -1 and not recognized magic value")

                    #ok, so we have the magic value (todo: this should really be the PID... it makes
                    #more sense for the clients to decide this themselves.
                    if pid == self.player.pid:
                        #The previous state is used for various stuff, like checking if we need
                        #to redraw the HUD. Thus copy it.
                        self.prev_state_player = copy.copy(self.player)
                        self.update_player(self.player, p)
                        continue

                    #first time we see this PID, so we need to create the structures to keep it.
                    if pid not in self.other_players.keys():
                        new_player = Player()
                        self.other_players[pid] = new_player
                        self.update_player(new_player, p)
                        client.scoreboard.add_player(new_player) #todo: duplication...
                        print(f"CLIENT: New player with pid {pid} connected!")
                    else:
                        self.update_player(self.other_players[pid], p)

            elif msg[0] == "player_disconnect":
                print(self.other_players)
                print("pid " + str(msg[1]) + " disconnected")
                if msg[1] in self.other_players:
                    client.scoreboard.remove_player(self.other_players[msg[1]])
                    self.other_players.pop(msg[1])

class Animation():
    def __init__(self, frames_glob_pattern=None, fps=60):
        self.frames = []
        if frames_glob_pattern:
            self.frames = self.load_frames_glob(frames_glob_pattern)
        self.fps = fps
        self.current_frame = 0
        self.since_last_frame = 0

    def load_frames_glob(self, path):
        for file in glob.glob(path):
            self.frames.append(pygame.image.load(file)).convert()

    def get_center_offset(self):
        return (self.frame_width/2, self.frame_height/2)

    def get_size(self):
        return (self.frame_width, self.frame_height)

    def reset(self):
        self.current_frame = 0
        self.since_last_frame = 0

    def next_frame(self, dt):
        num_frames = len(self.frames)
        seconds_per_frame = 1/self.fps
        self.since_last_frame += dt

        if self.since_last_frame < seconds_per_frame:
            return self.frames[self.current_frame%num_frames]
        else:
            retval = self.frames[self.current_frame%num_frames]
            self.current_frame += 1  #hopefully usually 1..
        return retval

    def load_frames_sheet(self, shape, path, scale=1.0):
        #shape=(8,8)
        srf = pygame.image.load(path)#.convert_alpha()
        srf_size = srf.get_size()
        if scale > 1.0:
            srf = pygame.transform.scale(srf, (int(srf_size[0] * scale), int(srf_size[1] * scale)))

        srf_size = srf.get_size()
        frame_w = srf_size[0]/shape[0]
        frame_h = srf_size[1]/shape[1]
        self.frame_width = frame_w
        self.frame_height = frame_h

        for fh in range(shape[1]):
            for fw in range(shape[0]):
                source_rect = pygame.Rect((frame_w * fw, frame_h * fh, frame_w, frame_h))
                img = pygame.Surface(source_rect.size, pygame.SRCALPHA)
                img.blit(srf, (0,0), source_rect)
                self.frames.append(img)
                #print("Added frame", source_rect)


if __name__ == '__main__':

       
    global game_over  #:(
    game_over = False

    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--server",  action="store", help="Start the server at given ip addr interface")
    parser.add_argument("-t", "--timelimit", action="store")
    parser.add_argument("-c", "--connect",  action="store", help="Start the server")

    args = parser.parse_args()


    if args.server:
        main_server(args)
        sys.exit(0)

    client = Client()
    client.args = args
    client.start_game()

    #we out
    print("Someone killd the game. See ya")
    #let's try to disconnect nicely. who cares if we can't.
    send_socket(client.client_socket, ["player_disconnect", client.player.name, client.player.pid], client.server_addr)
    pygame.quit()
