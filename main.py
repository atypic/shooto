import errno
import copy
import os
import argparse
import random
import pygame
import select
import datetime
from collections import deque 
import math
import pygame.locals
import pygame.image
from pygame import *
from pygame.math import Vector2
import glob
import itertools
import numpy as np
#from pytmx.util_pygame import load_pygame
#import pyscroll
#from opensimplex import OpenSimplex

import signal
import sys
from PIL import Image

PORT=4162

class GameMap():
    def __init__(self, mapfile=None, size=(2000,1000), server=False):
        self.size = size
            #ugghself.map = None
        #self.map_surface = pygame.Surface(size)
        #self.pixels = pygame.PixelArray(self.map_surface)
        self.pixels = None
        
        if not mapfile:
            for y in range(size[1]):
                self.genmap.append([0] * size[0])
                for x in range(size[0]):
                    v = gen.noise2d(2*x/size[0], 2*y/size[1])
                    self.genmap[y][x] = 1 if v > 0 else 0
                    #self.pixels[x,y] = pygame.Color(100,0,0) if v > 0 else pygame.Color(50,150,50)

        self.pixels = Image.open(mapfile)
        self.size = self.pixels.size
        self.pixels = np.swapaxes(np.asarray(self.pixels), 0, 1)
        if not server:
            self.map = pygame.image.load(mapfile).convert()#.convert_alpha()

        self.current_visible_surface = None
 
        self.tile_width = 1
        self.tile_height = 1

        self.spawnpoints = [[0,0], 
                            [self.size[0]-16, self.size[1] - 200],
                            [self.size[0]/2, self.size[1]/2]]

        #render the entire map.
        #self.map_surface = pygame.Surface((self.tile_width * size[0], self.tile_height * size[1]))
        #print(self.tile_width * size[0], self.tile_height * size[1])
        #draw the map.

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

        viewport.blit(self.current_visible_surface, (0,0))
        return (view_rect)

#just a datastructure
class Bullet():
    def __init__(self, pos = None, velocity = None):
        self.velocity = velocity
        self.rect = pygame.Rect(pos, (8,8))
        self.color = pygame.Color(255,0,0)
        self.type = 0
        #self.img = pygame.Surface((8,8))
        #self.img.fill(self.color)


class Player(pygame.sprite.Sprite):
    def __init__(self, pos=(0,0), frames=None, color=pygame.Color(255, 0, 0), client=False, hp=5):
        super().__init__()
        self.velocity = [0.,0.]
        self.grounded = False
        self.facing_left = False
       
        self.pid = -1
        
        self.client = client
        self.updates_without_events = 0
        self.cliaddr = None
        self.magic_value = None

        self.color = color
        self.img = pygame.Surface((16,16))
        self.img.fill(self.color)

        self.hitters = []
        self.hit_img = pygame.Surface((16,16))
        self.hit_img.fill((255,255,255))

        self.rect = pygame.Rect(pos, (16,16))
        self.posx = 0.0
        self.posy = 0.0

        #these are things that are fired and needs updating when time ticks.
        self.bullets = []
        self.name = "UnnamedPlayer"
        self.score = 0
        self.ready = False
        self.health = hp

        self.holding_up = False
        self.holding_down = False

        self.spawnpoint = 0
        self.cooldown = 0



    def update_color(self, col):
        self.color = col
        self.img.fill(self.color)

    def react(self, event_type, event_key, keystate):
        if event_type == pygame.KEYDOWN:
            if event_key == pygame.K_a:
                self.facing_left = True
                self.velocity[0] = -400
            if event_key == pygame.K_d:
                self.facing_left = False
                self.velocity[0] = 400
            if event_key == pygame.K_j:
                if self.grounded:
                    self.velocity[1] = -400
            if event_key == pygame.K_w:
                self.holding_up = True
            if event_key == pygame.K_s:
                self.holding_down = True
 
            if event_key == pygame.K_k:
                #fire weapon
                vel = []
                #holding up
                if self.holding_up:
                    vel = [0, -600]
                #down
                elif self.holding_down:
                    vel = [0, 600]
                else:
                    if self.facing_left:
                        vel = [-600, 0]
                    else:
                        vel = [600, 0]
                self.bullets.append(Bullet(pos = self.rect.center, velocity=vel))
                #print(f'added bullet at {self.rect.center}, speed {vel}')

        
        if event_type == pygame.KEYUP:
            #pressed keys
            if event_key == pygame.K_a and self.velocity[0] < 0:
                if keystate[pygame.K_d]:
                    self.facing_left = False
                    self.velocity[0] = 400
                else:
                    self.velocity[0] = 0
            if event_key == pygame.K_d and self.velocity[0] > 0:
                if keystate[pygame.K_a]:
                    self.facing_left = True
                    self.velocity[0] = -400
                else:
                    self.velocity[0] = 0
            if event_key == pygame.K_j and self.velocity[0] < 0:
                self.velocity[1] = 0
            if event_key == pygame.K_w:
                self.holding_up = False
            if event_key == pygame.K_s:
                self.holding_down = False
 


    #remember mappy needs to be a pixel array
    def update(self, mappy, dt):
        self.grounded = False
        self.velocity[1] += 1000. * dt   #gravity, but why is this fucked?

        delta_distance_x = self.velocity[0] * dt   
        delta_distance_y = self.velocity[1] * dt

        self.rect.x += delta_distance_x
        self.rect.y += delta_distance_y


        self.rect.x = max(0, min(mappy.size[0]-16, self.rect.x))
        self.rect.y = max(0, min(mappy.size[1]-16, self.rect.y))
        #px = pygame.PixelArray(mappy.map)
        px = mappy.pixels

        raylen = int(abs(delta_distance_y)) + 1
        
        #collision_value = mappy.map.map_rgb(255,0,0)  #what?
        collision_value = [255,0,0]

        #bottom collision, iterate all pixels and check for match.
        if self.velocity[1] >= 0: #we are falling, positive is down.
            for rpixl in range(self.rect.bottom, min(mappy.size[1], self.rect.bottom + raylen)):
                if (px[self.rect.centerx][rpixl] == collision_value).all():
                    self.rect.bottom = rpixl
                    #self.posy = self.rect.bottom
                    self.velocity[1] = 0
                    self.grounded = True
                    break
        
        #px.close()

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

        self.gmap = GameMap(mapfile='map1.png', server=True) #erk.

        #gamestate 0 is clock not running.
        self.gamestate = 0
    
        self.settings = {}
        self.settings['cooldown'] = 0.5
        self.settings['initial_hp'] = 5
        self.settings['round_length'] = 5

        self.timeleft = self.settings['round_length']

    def handle_queues(self):
        if len(self.meta_queue) > 0:
            for cliaddr, meta in self.meta_queue:
                if cliaddr not in self.cliaddr_to_pid.keys():
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
            for cliaddr, event in self.event_queue:
                pid = self.cliaddr_to_pid[cliaddr]

                if self.players[pid].cooldown == 0:
                    self.players[pid].react(event[2], event[3], event[6])  #react to events


                self.players[pid].updates_without_events = 0

            self.event_queue = []

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
                        self.players[pid2].hitters.append([0.5, pid2])
                        #only hit if not cooled down
                        if self.players[pid2].cooldown == 0:
                            self.players[pid2].health = max(self.players[pid2].health - 1, 0)
                        bullets_to_remove.append(bullet)
                        
                        #did we die? if so, set a new spawnpoint, but don't move the
                        #player until a cooldown.
                        if self.players[pid2].health == 0:
                            self.players[pid].score += 1.0
                            print(self.players[pid2], " died!")
                            sp = random.randrange(0, len(self.gmap.spawnpoints))
                            self.players[pid2].rect.x = self.gmap.spawnpoints[sp][0]
                            self.players[pid2].rect.y = self.gmap.spawnpoints[sp][1]
                            print("new position: ", self.gmap.spawnpoints[sp])
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

            #chech if everyone is ready!
            if self.gamestate == 0:
                ready_states = [p.ready for p in self.players.values()]
                if len(ready_states) > 0 and False not in ready_states:
                    self.timeleft = self.settings['round_length']
                    self.gamestate = 1


            print(self.gamestate)
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

            if diff.total_seconds() * 1000 > 20:
                #handle the queues!
                self.handle_queues()
            
                if self.gamestate == 0:
                    time_last_update = datetime.datetime.now()
                    continue
               

                for pid in self.players.keys():
                    self.players[pid].update(self.gmap, diff.total_seconds()) #collision detection.
                    self.players[pid].updates_without_events += 1
                    self.players[pid].cooldown = max(0, self.players[pid].cooldown - diff.total_seconds())

                    for pid2 in self.players.keys():
                        self.player_collision(pid, pid2)

                    #finally, figure out if bullets hit world objects
                    self.players[pid].bullet_collisions(self.gmap, diff.total_seconds()) #collision detection.
                 
                time_last_update = datetime.datetime.now()

            #handling done.
            diff = datetime.datetime.now() - time_last_update_2
            if diff.total_seconds() * 1000 > 20:
                if self.gamestate == 1 or self.gamestate == 2:
                    self.timeleft -= diff.total_seconds()
                self.update_clients()
                time_last_update_2 = datetime.datetime.now()

            #prune dead users..
            for pid in self.players.keys():
                if self.players[pid].updates_without_events > 10000:
                    #let's remove...
                    self.connected_clients.remove(self.players[pid].cliaddr)
                    self.recently_disconnected.append((self.players.cliaddr, pid))
                    p = self.players.pop(pid)
                    print(f"{p.name} disconnected!")

            
  
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
        self.pid += 1
        print(f"Created a new player: {name} at {cliaddr}")

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
            #check if we have already made a player for this client.
            pid = self.cliaddr_to_pid[cliaddr]
            self.players[pid].ready = True
        elif dat[0] == "player_disconnect":
            self.connected_clients.remove(cliaddr)
            pid = self.cliaddr_to_pid[cliaddr]
            self.recently_disconnected.append((cliaddr, pid))
            p = self.players.pop(pid)
            print(f"{p.name} disconnected!")
            print(self.recently_disconnected)


    def update_clients(self):
        state = ["state", [(p.pid, 
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
                            self.timeleft) for k, p in
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
    def __init__(self, lines=[], color = pygame.Color('black'), font = 'inconsolata.ttf', fontsize =
            20, bgcolor = (50,500,100,255)):
        self.lines = lines
        self.textsurface = pygame.Surface((1,1))
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
            max_row = max(row_surf, key=lambda x: x.get_width())
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
            self.textsurface.blit(line_surface, (0, max_height * rownum), special_flags =
                    pygame.BLEND_RGBA_MULT)
        

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
                                        special_flags = BLEND_RGBA_MULT
                                    )

            rownum += 1

        self.scoresurface = final_surface

def signal_handler(sig, frame):
    global game_over
    game_over = True


class Client():
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((400,400))

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

        self.player = Player(color = col)
        self.player.name = ""
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
            self.player.magic_value = random.randint(0,255)
            print("created socket")

        #attempt to send the connect packet.
        send_socket(self.client_socket, ["player_meta", self.player.name, self.player.color,
                                    self.player.magic_value], self.server_addr)
    
    def send_player_ready(self, server_addr=None):
        send_socket(self.client_socket, ["player_ready", self.player.magic_value], self.server_addr)
    

    def ending(self):
        global game_over
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
         
        while(not game_over and not ending_done):
            dt = clock.tick_busy_loop(fps) / 1000.
            self.screen.fill(bgcolor) 
            self.screen.blit(self.scoreboard.get_scoreboard_surface(), (10,10))
            self.receieve_state()
            pygame.display.flip()

            if self.gamestate == 0:
                self.opening()


    #select map, player name and bot opponents
    def opening(self):
        global game_over
        #render the name input box
        tib = TextInputBox("Name, then enter: ", (10,10))
        tib.entered_text = self.player.name

        active_box = tib
        opening_done = False
        bgcolor = (150, 150, 200, 255)
        tb = MultilineTextBox(bgcolor = bgcolor)
        plr_list = []
        old_plr_list = []
        last_update = datetime.datetime.now()
        connected = False
        fps = 60
        clock = pygame.time.Clock()
        send_player_ready = False
        name_locked = False

        infotxt = TextMessage("Enter: lock name. Press b to begin!", (0,0), 0, fontsize=16)
         
        while(not game_over and not opening_done):
            dt = clock.tick_busy_loop(fps) / 1000.

            self.screen.fill(bgcolor)
            active_box.render_text(self.screen)

            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        self.player.name = active_box.entered_text
                        name_locked = True
                    if event.key == pygame.K_BACKSPACE:
                        active_box.del_char()
                    if name_locked:
                        if event.key == pygame.K_b:
                            send_player_ready = True
                            #opening_done = True
                    else:
                        if event.key in self.allowed_keys:
                            active_box.add_char(pygame.key.name(event.key))
            

            if (datetime.datetime.now() - last_update).total_seconds() > 0.2:
                if not send_player_ready:
                    self.connect_server(server_addr=args.connect)
                else:
                    self.send_player_ready(server_addr=args.connect)

                last_update = datetime.datetime.now()

            self.receieve_state()   #update the other_players thingy. 
            
            plr_info = [(plr.name, plr.ready) for plr in self.other_players.values()]
            plr_list = [p[0] + " ready!" if p[1] else p[0] for p in plr_info]

            if self.player.pid != -1:
                to_print = self.player.name
                if self.player.ready:
                    to_print = to_print + " ready!"
                plr_list.append(to_print)

            if set(plr_list) != set(old_plr_list):
                print("update player list: ", plr_list)
                tb.update(plr_list)
                old_plr_list = plr_list

            self.screen.blit(tb.get_surface(), (10, 100))
            self.screen.blit(infotxt.get_surface(), (10, 250))
            pygame.display.flip()
           
            #go game
            if self.gamestate == 1:
                self.main_game()

        return

    def main_game(self):
        global game_over
        gmap = GameMap(mapfile='map1.png')
        zoom = 1.0
        fps = 60.
        clock = pygame.time.Clock()
        
        write_rdy = []
        read_rdy = []

        eventcount = 0

        bullet_img = pygame.Surface((8,8))
        bullet_img.fill(pygame.Color(255,0,100))


        t_last_update = datetime.datetime.now()
        while not game_over:
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
                        msg = ["event", eventcount, event.type, event.key, client.player.name, dt, keystate]
                        send_socket(client.client_socket, msg, client.server_addr)
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
                    break #all we need to know.

            client.screen.blit(blitimg, (client.player.rect.x - v_rect.left, client.player.rect.y - v_rect.top))

            #in case we haven't gotten a new update yet, let's predict where the clients are, assuming
            #they kept the velocity we saw last.
            for name, plr in client.other_players.items():
                if (datetime.datetime.now() - t_last_update).total_seconds() > dt:
                    plr.velocity[1] += 1000. * dt   #is this even correct. i don't know. 
                    plr.rect.x += plr.velocity[0] * dt
                    plr.rect.y += plr.velocity[1] * dt

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

                client.screen.blit(blitimg, (plr.rect.x - v_rect.left, plr.rect.y - v_rect.top))


            #draw the hud
            if client.prev_state_player.health != client.player.health:
                client.health_bar.update_text("HP: " + str(client.player.health))

            client.timeleft_bar.update_text("{:.1f}".format(client.timeleft))
            client.screen.blit(client.timeleft_bar.get_surface(), (180, 10))

            hp_srf = client.health_bar.get_surface()
            client.screen.blit(hp_srf, (310, 10))
        
            if client.gamestate == 2:
                client.ending()
            else:
                client.scoreboard.update_scoreboard_surface()
                client.screen.blit(client.scoreboard.get_scoreboard_surface(), (10,10))

            pygame.display.flip()

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
                for p in msg[1]:
                    
                    #check if we got back our own pid
                    #usually first connect
                    if self.player.pid == -1:
                        if p[10] == self.player.magic_value:
                            self.player.pid = p[0]

                    #this is us.
                    if p[0] == self.player.pid:
                        #copy the old state 
                        self.prev_state_player = copy.copy(self.player)

                        self.player.rect.x = p[2]
                        self.player.rect.y = p[3]
                        self.player.velocity = [p[4],p[5]]
                        self.player.bullets = p[6]
                        self.player.score = p[7]
                        self.player.hitters = p[8]
                        self.player.magic_value = p[10]
                        self.player.ready = p[11]
                        self.gamestate = p[12]
                        self.player.health = p[13]
                        self.timeleft = p[14]

                        if p[9] != self.player.color:
                            self.player.update_color(p[9])

                        continue

                    #print("other player, got this:", p)
                    if p[0] not in self.other_players.keys():
                        print("made a new friend")
                        self.other_players[p[0]] = Player()
                        self.other_players[p[0]].name = p[1]
                        self.other_players[p[0]].rect.x = p[2]
                        self.other_players[p[0]].rect.y = p[3]
                        self.other_players[p[0]].velocity = [p[4],p[5]]
                        self.other_players[p[0]].bullets = p[6]
                        self.other_players[p[0]].score = p[7]
                        self.other_players[p[0]].hitters = p[8]
                        self.other_players[p[0]].magic_value = p[10]
                        self.other_players[p[0]].ready = p[11]

                        if p[9] != self.other_players[p[0]].color:
                            self.other_players[p[0]].update_color(p[9])

     
                        client.scoreboard.add_player(self.other_players[p[0]]) #todo: duplication...

                    self.other_players[p[0]].name = p[1]
                    self.other_players[p[0]].rect.x = p[2]
                    self.other_players[p[0]].rect.y = p[3]
                    self.other_players[p[0]].velocity = [p[4],p[5]]
                    self.other_players[p[0]].bullets = p[6]
                    self.other_players[p[0]].score = p[7]
                    self.other_players[p[0]].hitters = p[8]
                    self.other_players[p[0]].magic_value = p[10]
                    self.other_players[p[0]].ready = p[11]

                    if p[9] != self.other_players[p[0]].color:
                        self.other_players[p[0]].update_color(p[9])

                   
            elif msg[0] == "player_disconnect":
                print(self.other_players)
                print("pid " + str(msg[1]) + " disconnected")
                if msg[1] in self.other_players:
                    client.scoreboard.remove_player(self.other_players[msg[1]])
                    self.other_players.pop(msg[1])


if __name__ == '__main__':

    global game_over  #:(
    game_over = False

    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--server",  action="store", help="Start the server at given ip addr\
            interface")
    parser.add_argument("-c", "--connect",  action="store", help="Start the server")

    args = parser.parse_args()


    if args.server:
        main_server(args)
        sys.exit(0)

    client = Client()
    client.args = args
    client.opening()
    
    #we out
    print("Someone killd the game. See ya")
    #let's try to disconnect nicely. who cares if we can't.
    send_socket(client.client_socket, ["player_disconnect", client.player.name, client.player.pid], client.server_addr)
    pygame.quit()


