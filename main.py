import errno
import os
import argparse
import random
import pygame
import matplotlib.pyplot as plt
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
#from pytmx.util_pygame import load_pygame
#import pyscroll
from opensimplex import OpenSimplex

import signal
import sys

PORT=4162

def line_intersect(p1,p2,p3,p4):
        d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
        if d == 0:
            return None
        u = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0]))/d
        v = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p3[0]))/d

        if (u < 0.0 or u > 1.0):
            return None
        if (v < 0.0 or v > 1.0):
            return None
        
        isect = [None,None]
        isect[0] = p1[0] + u * (p2[0] - p1[0])
        isect[1] = p1[1] + u * (p2[1] - p1[1])

        return isect


class GameMap():
    def __init__(self, mapfile=None, size=(2000,1000)):
        gen = OpenSimplex()
        self.size = size
        self.genmap = []
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

        else:
            self.map = pygame.image.load(mapfile).convert()#.convert_alpha()
            #self.pixels = pygame.PixelArray(map_png)
            self.size = self.map.get_size()

        self.current_visible_surface = None
 
        self.tile_width = 1
        self.tile_height = 1
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
    def __init__(self, pos=(0,0), frames=None, color=pygame.Color(255, 0, 0)):
        super().__init__()
        self.velocity = [0.,0.]
        self.grounded = False
        self.facing_left = False

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
        self.pid = -1
        self.score = 0

        self.holding_up = False
        self.holding_down = False

    def update_color(self, col):
        self.color = col
        self.img.fill(self.color)

    def react(self, event_type, event_key):
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
            keystate = pygame.key.get_pressed()
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
 


  
    def update(self, mappy, dt):
        self.grounded = False
        self.velocity[1] += 1000. * dt   #gravity, but why is this fucked?

        delta_distance_x = self.velocity[0] * dt   
        delta_distance_y = self.velocity[1] * dt

        self.rect.x += delta_distance_x
        self.rect.y += delta_distance_y


        self.rect.x = max(0, min(mappy.size[0]-16, self.rect.x))
        self.rect.y = max(0, min(mappy.size[1]-16, self.rect.y))
        px = pygame.PixelArray(mappy.map)

        raylen = int(abs(delta_distance_y)) + 1
        
        collision_value = mappy.map.map_rgb(255,0,0)
        #bottom collision, iterate all pixels and check for match.
        if self.velocity[1] >= 0: #we are falling, positive is down.
            for rpixl in range(self.rect.bottom, min(mappy.size[1], self.rect.bottom + raylen)):
                if px[self.rect.centerx][rpixl] == collision_value:
                    self.rect.bottom = rpixl
                    #self.posy = self.rect.bottom
                    self.velocity[1] = 0
                    self.grounded = True
                    break
        
        px.close()

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
        px = pygame.PixelArray(mappy.map)
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
        
            collision_value = mappy.map.map_rgb(255,0,0)
            #bottom collision, iterate all pixels and check for match.
            if b.velocity[1] > 0: #bullets going down
                if self.grounded:
                    self.bullets.remove(b)
                    continue
                for rpixl in range(b.rect.bottom, min(mappy.size[1], b.rect.bottom + raylen)):
                    if px[b.rect.centerx][rpixl] == collision_value:
                        self.bullets.remove(b)
                        break
            #bullets going up
            elif b.velocity[1] < 0:
                #print(b.rect.top - raylen, b.rect.top)
                for rpixl in range(max(0, b.rect.top - raylen), b.rect.top):
                    if px[b.rect.centerx][rpixl] == collision_value:
                        self.bullets.remove(b)
                        break
 
        px.close()
        
        return
            

import socket
import pickle

from collections import defaultdict

class ShootoServer():
    def __init__(self):
        #socket and shit.
        self.connected_clients = []
        self.recently_disconnected = []

        self.players = {}
        self.event_queue = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('localhost', PORT))
        self.servertime = 0
        self.socket.setblocking(0)         

        self.bullet_hits = defaultdict(list)
        self.pid = 0
        self.cliaddr_to_pid = {}

        pygame.init()
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
        screen = pygame.display.set_mode((400,400))
        self.gmap = GameMap(mapfile='map1.png')


    def server_main(self):
        print("starting server")
        global game_over
        #start a socket, listening for incoming packets.
        #keep a game loop that updates the clients with 
        #a gamestate (i.e. the position and velocity of all players)
        #every 100ms or so.
        clock = pygame.time.Clock()

        t = datetime.datetime.now()
        dt = 0
        time_last_update = datetime.datetime.now()
        time_last_update_2 = datetime.datetime.now()
        while(not game_over):
            dt = datetime.datetime.now() - t
            t = datetime.datetime.now()
            #t = clock.tick_busy_loop(ups) / 1000.
            #might have a new connection.
            ready_to_read, ready_to_write, in_error = \
               select.select(
                  [self.socket],   #readers
                  [self.socket],  #writers
                  [self.socket], #errors
                  0)


            #print("claims to be ready to recieve: ", ready_to_read)
            #this needs to happen all the time.
            if self.socket in ready_to_read:
                self.receive_from_clients()
            
            diff = datetime.datetime.now() - time_last_update
            if diff.total_seconds() * 1000 > 20:
                if len(self.event_queue) >  0:
                    for cliaddr, event in self.event_queue:
                        pid = self.cliaddr_to_pid[cliaddr]
                        #print(f"got event from {pid}, {event}")
                        #todo: do some stuff with respect to the event[0] timestamp thing.
                        #self.players[pid].name = event[3]  #eeeeh...
                        self.players[pid].react(event[2], event[3])  #react to events...
                    self.event_queue = []
              
                for pid in self.players.keys():
                    self.players[pid].update(self.gmap, diff.total_seconds()) #collision detection.
                
                #all players and bullets moved, did the bullets hit anything
                for pid in self.players.keys():
                    for pid2 in self.players.keys():
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
                                        self.players[pid].score += 1.0
                                        bullets_to_remove.append(bullet)

                            #this removes the bullets shot that hit something.
                            self.players[pid].bullets = [x for x in self.players[pid].bullets if x not in
                                                        bullets_to_remove]

                #finally, figure out if bullets hit world objects
                for pid in self.players.keys():
                    self.players[pid].bullet_collisions(self.gmap, diff.total_seconds()) #collision detection.
                 
                time_last_update = datetime.datetime.now()

            diff = datetime.datetime.now() - time_last_update_2
            if diff.total_seconds() * 1000 > 20:
                wr_rdy, rd_rdy, in_error = select.select( [self.socket], [self.socket], [], 0) #errors

                self.update_clients(wr_rdy)
                time_last_update_2 = datetime.datetime.now()

   
    def receive_from_clients(self):
        dat, cliaddr = rcv_socket(self.socket)
        #filter on message type here i guess.
        if not dat:
            return

        if dat[0] == "event":
            self.event_queue.append((cliaddr, dat))
            #print("got event!")
        elif dat[0] == "player_meta":
            self.players[self.pid] = Player(color=dat[2])
            self.players[self.pid].name = dat[1]
            self.cliaddr_to_pid[cliaddr] = self.pid
            self.connected_clients.append(cliaddr)
            self.players[self.pid].pid = self.pid
            print(f"new player {dat[1]}  got pid {self.pid}.")
            self.pid += 1
            #pong back to client
        elif dat[0] == "player_disconnect":
            self.connected_clients.remove(cliaddr)
            pid = self.cliaddr_to_pid[cliaddr]
            self.recently_disconnected.append((cliaddr, pid))
            p = self.players.pop(pid)
            print(f"{p.name} disconnected!")
            print(self.recently_disconnected)


    def update_clients(self, wr_rdy):
        state = ["state", [(p.pid, 
                            p.name, 
                            p.rect.x, p.rect.y, 
                            p.velocity[0], p.velocity[1],
                            p.bullets, 
                            p.score, 
                            p.hitters,
                            p.color) for k, p in
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
    
   
class ClientInputPacket():
    def __init__(self):
        #python events
        self.timestamp = 0
        self.events = []

class ClientUpdatePacket():
    def __init__(self):
        self.servertime = 0
        self.playerpos = {}
        self.playervel = {}

def main_server(args):
    server = ShootoServer()
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


class TextMessage():
    def __init__(self, text, position, duration, surface_size=None, font='inconsolata.ttf', fontsize=32):
        green = (0, 255, 0) 
        blue = pygame.Color('black')
        font = pygame.font.Font(font, fontsize) 
        self.rtext = font.render(text, True, blue)
        #if not surface_size:
        #    surface_size = self.rtext.get_size()
        #self.alpha_img = pygame.Surface(surface_size, pygame.SRCALPHA)
        #self.alpha_img.fill((255,255,255,255))
        #self.rtext.blit(self.alpha_img, (0,0), special_flags=pygame.BLEND_RGBA_MULT)

        self.textrect = self.rtext.get_rect()
        self.textrect.topleft = position
        self.timeleft = duration

    def get_surface(self, dt):
        if (self.timeleft > 0) or (self.timeleft == 0):
            self.timeleft -= dt
            return self.rtext
        else:
            print("timeleft", self.timeleft)
            return None
   
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

        self.allowed_keys = [
            pygame.K_a,
            pygame.K_b,
            pygame.K_c,
            pygame.K_d,
            pygame.K_e,
            pygame.K_f,
            pygame.K_g,
            pygame.K_h,
            pygame.K_i,
            pygame.K_j,
            pygame.K_k,
            pygame.K_l,
            pygame.K_m,
            pygame.K_n,
            pygame.K_o,
            pygame.K_p,
            pygame.K_q,
            pygame.K_r,
            pygame.K_s,
            pygame.K_t,
            pygame.K_u,
            pygame.K_v,
            pygame.K_w,
            pygame.K_x,
            pygame.K_y,
            pygame.K_z]

        self.client_socket = None
        self.server_addr = None
   
    def connect_server(self, player, server_addr=None):
        global game_over

        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if server_addr is None:
            self.server_addr = ('localhost', PORT)
        else:
            hostname, port = server_addr.split(':')
            self.server_addr = (hostname, int(port))
        self.client_socket.setblocking(0) 

        meta_sent = False
        while (player.pid == -1 and not game_over):
            read_rdy, write_rdy, in_err = select.select([self.client_socket],[self.client_socket],[self.client_socket], 0)

            if (self.client_socket in write_rdy) and not meta_sent:
                print("Attempting to connect!")
                send_socket(self.client_socket, ["player_meta", player.name, player.color], self.server_addr)
                meta_sent = True
        
            #don't start until we've got a pid
            print(f"waiting for reply, meta sent? {meta_sent}")
            msg, srv = rcv_socket(self.client_socket)
            if msg is None:
                print("GOT NONE WHY?")
                continue
            if msg[0] == "state":
                print("i got state!")
                for p in msg[1]:
                    if p[1] == player.name:
                        if p[0] != -1:
                            player.pid = p[0]
                        else:
                            print("player name in use you sic fuk, chose another!")
                            return -1
        return player.pid

    #select map, player name and bot opponents
    def opening(self):
        global game_over
        #render the name input box
        tib = TextInputBox("Name, then enter: ", (10,10))
        opening_done = False
        while(not game_over and not opening_done):
            self.screen.fill((255,255,100))
            tib.render_text(self.screen)

            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        return tib.entered_text
                        print("OK, here we go. Enter pressed, starting game")
                        if ret != -1:
                            opening_done = True
                    if event.key == pygame.K_BACKSPACE:
                        tib.del_char()
                    if event.key in self.allowed_keys:
                        tib.add_char(pygame.key.name(event.key))
            
            pygame.display.flip()
        #todo: input the server address (... :port)
        return 
   
    def game(self):
        return

if __name__ == '__main__':

    global game_over  #:(
    game_over = False

    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--server",  action="store_true", help="Start the server")
    parser.add_argument("-c", "--connect",  action="store", help="Start the server")

    args = parser.parse_args()


    if args.server:
        main_server(args)
        sys.exit(0)

    client = Client()
    player_name = client.opening()
    
    random.seed(datetime.datetime.now())
    col = ( random.randint(0,255), 
            random.randint(0,255),
            random.randint(0,255))

    player = Player(color = col)
    player.name = player_name
    player.rect.x = 600
    player.rect.y = 0
    other_players = {}

    client.connect_server(player, server_addr=args.connect)

    #else, let's connect to the server.
    #client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #server_addr = ('localhost', PORT)
    #client_socket.setblocking(0)         

    gmap = GameMap(mapfile='map1.png')
    zoom = 1.0
    fps = 60.
    clock = pygame.time.Clock()


    
    write_rdy = []
    read_rdy = []
 
    scoreboard = ScoreBoard()
    scoreboard.add_player(player)
    eventcount = 0


    #overlay_texts = {}

    bullet_img = pygame.Surface((8,8))
    bullet_img.fill(pygame.Color(255,0,100))

    bullet_hits = defaultdict(list)

    while not game_over:
        dt = clock.tick_busy_loop(fps) / 1000.


        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game_over = True
            if event.type == pygame.KEYDOWN or event.type == pygame.KEYUP:
                _, write_rdy, in_err = select.select([],[client.client_socket],[client.client_socket], 0)
                #send event to server
                if client.client_socket in write_rdy:
                    msg = ["event", eventcount, event.type, event.key, player.name, dt]
                    send_socket(client.client_socket, msg, client.server_addr)


        #receieve all player stats
        read_rdy, _, in_err = select.select([client.client_socket],[],[client.client_socket], 0)

        for client.client_socket in read_rdy:
            msg, srv = rcv_socket(client.client_socket)
            if msg[0] == "state":
                for p in msg[1]:
                    if p[1] == player.name:
                        player.rect.x = p[2]
                        player.rect.y = p[3]
                        player.velocity = [p[4],p[5]]
                        player.bullets = p[6]
                        player.score = p[7]
                        player.hitters = p[8]

                        if p[9] != player.color:
                            player.update_color(p[9])

                        continue

                    #print("other player, got this:", p)
                    if p[0] not in other_players.keys():
                        print("made a new friend")
                        other_players[p[0]] = Player()
                        other_players[p[0]].name = p[1]
                        other_players[p[0]].rect.x = p[2]
                        other_players[p[0]].rect.y = p[3]
                        other_players[p[0]].velocity = [p[4],p[5]]
                        other_players[p[0]].bullets = p[6]
                        other_players[p[0]].score = p[7]
                        other_players[p[0]].hitters = p[8]

                        if p[9] != other_players[p[0]].color:
                            other_players[p[0]].update_color(p[9])

     
                        scoreboard.add_player(other_players[p[0]]) #todo: duplication...

                    other_players[p[0]].name = p[1]
                    other_players[p[0]].rect.x = p[2]
                    other_players[p[0]].rect.y = p[3]
                    other_players[p[0]].velocity = [p[4],p[5]]
                    other_players[p[0]].bullets = p[6]
                    other_players[p[0]].score = p[7]
                    other_players[p[0]].hitters = p[8]

                    if p[9] != other_players[p[0]].color:
                        other_players[p[0]].update_color(p[9])




                   
            elif msg[0] == "player_disconnect":
                print(other_players)
                print("pid " + str(msg[1]) + " disconnected")
                if msg[1] in other_players:
                    scoreboard.remove_player(other_players[msg[1]])
                    other_players.pop(msg[1])

            #print(f"Message received: {pickle.loads(b''.join(chunks))}")
            #todo: probably decode.


        v_rect = gmap.blit_visible_surface((player.rect.x, player.rect.y), client.screen, zoom)

        #draw the players own bullets... 
        blitimg = player.img
        for b in player.bullets:
            #bullets is in world coords.
            dest_x = max(0, min(b.rect.x - v_rect.left, client.screen.get_width()))
            dest_y = max(0, min(b.rect.y - v_rect.top, client.screen.get_height()))
            client.screen.blit(bullet_img, (dest_x, dest_y))

        #also, were we hit by some bullet?
        #print(player.hitters)
        for timeleft, h in player.hitters:
            if timeleft > 0.0:
                blitimg = player.hit_img
                break #all we need to know.

        client.screen.blit(blitimg, (player.rect.x - v_rect.left, player.rect.y - v_rect.top))

        for name, plr in other_players.items():

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


        scoreboard.update_scoreboard_surface()
        client.screen.blit(scoreboard.get_scoreboard_surface(), (10,10))

        pygame.display.flip()

    #we out
    print("Someone killd the game. See ya")
    #let's try to disconnect nicely. who cares if we can't.
    send_socket(client.client_socket, ["player_disconnect", player.name, player.pid], client.server_addr)
    pygame.quit()
