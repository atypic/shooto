from collections import defaultdict
import datetime
import socket
import copy
import argparse
import random
import pygame
import pygame_menu
import select
import datetime
from collections import deque
import pygame.locals
import pygame.image
import pygame.time
from pygame import Rect
import numpy as np
from shootoserver import ShootoServer
from utils import *

from PIL import Image


class Client():
    def __init__(self):
        pygame.init()
        self.screeenwidth = 1600
        self.screenheight = 1200
        self.screen = pygame.display.set_mode(
            (self.screeenwidth, self.screenheight))

        self.allowed_keys = [pygame.K_a, pygame.K_b, pygame.K_c, pygame.K_d, pygame.K_e, pygame.K_f,
                             pygame.K_g, pygame.K_h, pygame.K_i, pygame.K_j, pygame.K_k, pygame.K_l,
                             pygame.K_m, pygame.K_n, pygame.K_o, pygame.K_p, pygame.K_q, pygame.K_r,
                             pygame.K_s, pygame.K_t, pygame.K_u, pygame.K_v, pygame.K_w, pygame.K_x,
                             pygame.K_y, pygame.K_z]

        self.client_socket = None
        self.server_addr = None
        self.other_players = {}

        self.args = None
        self.pending_inputs = []

        random.seed(datetime.datetime.now())
        col = (random.randint(0, 255),
               random.randint(0, 255),
               random.randint(0, 255))

        self.last_packet_ts = None
        # makes a new player...
        self.player = Player()
        self.player.net_state.color = col
        self.player.net_state.name = "Jumbo"
        self.player.net_state.rect.x = 600
        self.player.net_state.rect.y = 0
        self.player.net_state.pid = -1

        self.scoreboard = ScoreBoard()
        self.scoreboard.add_player(self.player)

        self.health_bar = TextMessage(
            "HP: " + str(self.player.net_state.health), (0, 0), 0)

        self.gamestate = 0
        self.timeleft = 0.0
        self.timeleft_bar = TextMessage("{:.1f}".format(self.timeleft),
                                        (0, 0),
                                        0,
                                        fontsize=20)

        # first state packet is 0 or above.
        self.send_seq_nr = 0
        self.client_shutdown = False

    def start_game(self):
        while self.client_shutdown == False:
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
            self.client_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM)
            if server_addr is None:
                self.server_addr = ('localhost', PORT)
            else:
                hostname, port = server_addr.split(':')
                self.server_addr = (hostname, int(port))
            self.client_socket.setblocking(0)
            # generate a magic value
            self.player.magic_value = random.randint(0, 10000)
            print(
                f"CLIENT: created socket, my magic number is {self.player.net_state.magic_value}")

        # attempt to send the connect packet.
        send_socket(self.client_socket, ["player_meta", self.player.net_state.name, self.player.net_state.color,
                                         self.player.net_state.magic_value], self.server_addr)

    def send_player_ready(self, server_addr=None):
        send_socket(self.client_socket, [
                    "player_ready", self.player.net_state.name, self.player.net_state.magic_value], self.server_addr)

    # gamestate 2
    def ending(self):
        # render the name input box
        ending_done = False
        bgcolor = (200, 150, 100, 255)
        tb = MultilineTextBox(bgcolor=bgcolor)
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
            self.screen.blit(
                self.scoreboard.get_scoreboard_surface(), (10, 10))
            self.receieve_state()
            pygame.display.flip()

    def opening(self):
        # render the name input box
        # tib = TextInputBox("Name, then enter: ", (10,10))
        # tib.entered_text = self.player.name
        # _tib = pygame_menu.widgets.TextInput(label="Test", textinput_id='name_input')

        # send_player_ready = False
        print(self.player.net_state.name)

        def menu_start_game(self, text):
            print("We are going ready!")
            self.player.net_state.ready = True
            self.send_player_ready(server_addr=self.args.connect)

        def menu_player_change_name(text):
            self.player.name = text

        menu = pygame_menu.Menu("Shooto!", 800, 800)
        menu.add.text_input('Player name: ', default=self.player.net_state.name, textinput_id="player_name",
                            onchange=menu_player_change_name)
        menu.add.button('Mark ready!', menu_start_game, self,
                        menu.get_widget("player_name").get_value())
        menu.add.label("Players: ", label_id='playerlist')

        # active_box = tib
        opening_done = False
        bgcolor = (150, 150, 200, 255)
        # tb = MultilineTextBox(bgcolor = bgcolor)
        plr_list = []
        old_plr_list = []
        last_update = datetime.datetime.now()
        connected = False
        fps = 60
        self.clock = pygame.time.Clock()
        name_locked = False

        # this is the lobby state...
        while self.gamestate == 0:
            dt = self.clock.tick_busy_loop(fps) / 1000.
            self.screen.fill(bgcolor)

            if menu.is_enabled():
                menu.update(pygame.event.get())
                menu.draw(self.screen)

            if (datetime.datetime.now() - last_update).total_seconds() > 0.2:
                self.connect_server(server_addr=self.args.connect)

                last_update = datetime.datetime.now()

            self.receieve_state()  # update the other_players thingy.

            # Now we create a list of all the players, and jankily mark the ready players as ready.
            plr_info = [(plr.net_state.name, plr.net_state.ready, plr.net_state.pid)
                        for plr in self.other_players.values()]
            plr_list = [(p[2], p[0] + " ready!") if p[1]
                        else (p[2], p[0]) for p in plr_info]

            # I AM SORRY ABOUT THIS FUTURE ME, I SUCK AND THIS SORTA WORKS so... i kept it.
            # Add ourselves to the list of players.
            if self.player.net_state.pid != -1:
                to_print = self.player.net_state.name
                if self.player.net_state.ready:
                    print("noew aready")
                    to_print = to_print + " ready!"
                plr_list.append((self.player.net_state.pid, to_print))

            # nowwww we need to be careful when we update the list of players.
            for pid, name in plr_list:
                if(pid == -1):
                    continue
                label_id = f"lobbylist_{pid}"
                if menu.get_widget(label_id):
                    menu.get_widget(label_id).set_title(name)
                else:
                    menu.add.label(name, label_id=label_id)

            pygame.display.flip()

    # gamestate 1 (main game)
    def main_game(self):
        self.gmap = GameMap(mapfile='hugemap.png')
        zoom = 1.0
        fps = 60.
        clock = pygame.time.Clock()

        # write_rdy = []
        # read_rdy = []

        self.bullet_img = pygame.Surface((8, 8))
        self.bullet_img.fill(pygame.Color(255, 0, 100))

        t_last_update = datetime.datetime.now()
        while self.gamestate == 1 and self.client_shutdown == False:
            dt = clock.tick_busy_loop(fps) / 1000.  # we update at 60 fps. dt in seconds.

            # this is the state from the server, we update our world.
            self.receieve_state()
            # apply all the events since last update.
            self.handle_pygame_events(dt)
            self.draw_client_viewport(dt, zoom, t_last_update)

    def handle_pygame_events(self, dt):
        eventcount = 0
        _, write_rdy, in_err = select.select(
            [], [self.client_socket], [self.client_socket], 0)

        now = pygame.time.get_ticks()
        last = None
        if self.last_packet_ts:
            last = self.last_packet_ts
        else:
            last = now
        dt_sec = (now - last)/1000.0
        self.last_packet_ts = now

        msg = []
        # send all events to the server.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                msg = ["player_disconnect"]
                self.client_shutdown = True
                print("Client shutting down!")
                
            if event.type == pygame.KEYDOWN or event.type == pygame.KEYUP:
                keystate = pygame.key.get_pressed()

                if self.client_socket in write_rdy:
                    keystate = pygame.key.get_pressed()
                    msg = ["event", eventcount, event.type, event.key, self.player.net_state.name, dt_sec,
                           keystate, self.player.net_state.last_applied_event_id, dt_sec]
                    self.player.net_state.last_applied_event_id += 1

                send_socket(self.client_socket, msg, self.server_addr)

                # but also update local player with this information. (client side prediction)
                self.player.react(event.type, event.key, keystate, dt_sec, self.gmap)
                
                # store events and time it was applied for later reconciliation
                self.pending_inputs.append(msg)

            # print(f"Message received: {pickle.loads(b''.join(chunks))}")

    def draw_client_viewport(self, dt, zoom, t_last_update):
        # blit the current visible part of the map
        v_rect = self.gmap.blit_visible_surface(
            (self.player.net_state.rect.x, self.player.net_state.rect.y), self.screen, zoom)

        # draw the players own bullets...
        blitimg = self.player.img
        for b in self.player.net_state.bullets:
            # bullets is in world coords.
            dest_x = max(0, min(b.rect.x - v_rect.left,
                         self.screen.get_width()))
            dest_y = max(0, min(b.rect.y - v_rect.top,
                         self.screen.get_height()))
            self.screen.blit(self.bullet_img, (dest_x, dest_y))

        # also, were we hit by some bullet?
        # print(player.hitters)
        for timeleft, h in self.player.hitters:
            if timeleft > 0.0:
                blitimg = self.player.hit_img
                break  # we have been hit.

        if self.player.net_state.status == PlayerState.dead:
            death_anim_pos = (self.player.net_state.rect.centerx -
                              self.player.death_anim.get_center_offset()[
                                  0] - v_rect.left,
                              self.player.net_state.rect.centery -
                              self.player.death_anim.get_center_offset()[1] - v_rect.top)
            self.screen.blit(
                self.player.death_anim.next_frame(dt), death_anim_pos)
            if self.player.cooldown == 0:
                self.player.death_anim.reset()
        else:
            # This draws the player using the local position stored.
            self.screen.blit(blitimg, (self.player.net_state.rect.x -
                             v_rect.left, self.player.net_state.rect.y - v_rect.top))

        self.draw_enemies(dt, t_last_update, v_rect)
        self.draw_client_hud()
        return

    # This "should" simply draw the enemies, but currently
    # it also interpolates them and shit, which is annoying
    # and should be moved to the receving portion.
    def draw_enemies(self, dt, t_last_update, v_rect):
        # Enemy prediction.
        # in case we haven't gotten a new update yet, let's predict where the selfs are, assuming
        # they kept the velocity we saw last.
        for pid, plr in self.other_players.items():
            if (datetime.datetime.now() - t_last_update).total_seconds() > dt:
                # is this even correct. i don't know.
                plr.net_state.velocity[1] += 1000. * dt
                plr.net_state.rect.x += int(plr.net_state.velocity[0] * dt)
                plr.net_state.rect.y += int(plr.net_state.velocity[1] * dt)

            blitimg = plr.img
            for b in plr.net_state.bullets:
                # bullets is in world coords.
                dest_x = max(0, min(b.rect.x - v_rect.left,
                             self.screen.get_width()))
                dest_y = max(0, min(b.rect.y - v_rect.top,
                             self.screen.get_height()))
                self.screen.blit(self.bullet_img, (dest_x, dest_y))

            for timeleft, h in plr.hitters:
                if timeleft > 0.0:
                    blitimg = plr.hit_img
                    break  # all we need to know.

            if plr.net_state.status == PlayerState.dead:
                death_anim_pos = (plr.net_state.rect.centerx -
                                  plr.death_anim.get_center_offset()[
                                      0] - v_rect.left,
                                  plr.net_state.rect.centery -
                                  plr.death_anim.get_center_offset()[1] - v_rect.top)
                self.screen.blit(plr.death_anim.next_frame(dt), death_anim_pos)
                if plr.cooldown == 0:
                    plr.death_anim.reset()
            else:
                self.screen.blit(
                    blitimg, (plr.net_state.rect.x - v_rect.left, plr.net_state.rect.y - v_rect.top))

    def draw_client_hud(self):
        self.health_bar.update_text("HP: " + str(self.player.net_state.health))

        self.timeleft_bar.update_text("{:.1f}".format(self.timeleft))
        self.screen.blit(self.timeleft_bar.get_surface(), (180, 10))

        hp_srf = self.health_bar.get_surface()
        self.screen.blit(hp_srf, (310, 10))

        self.scoreboard.update_scoreboard_surface()
        self.screen.blit(self.scoreboard.get_scoreboard_surface(), (10, 10))

        pygame.display.flip()

        # gamestate changed
        return

    def update_player(self, player, state):
        # don't update our own name because this breaks the opening
        if player != self.player:
            player.net_state.name = state.name

        player.net_state = state

        if state.color != self.player.net_state.color:
            self.player.update_color(state.color)


    #Receive state of all players (including self) from the server.
    def receieve_state(self):
        if self.client_socket:
            read_rdy, _, in_err = select.select(
                [self.client_socket], [], [self.client_socket], 0)
        else:
            return
        for self.client_socket in read_rdy:
            msg, srv = rcv_socket(self.client_socket)
            if msg[0] == "game_statechange":
                self.gamestate = msg[1]
                print("Reveived message about state change to ", msg[1])

            if msg[0] == "state":
                # msg2 is depickled, contains 
                # PlayerNetState objects for all connected entities
                for player_netstate in msg[2]:
                    pid = player_netstate.pid

                    # PIDs are generated on the server, so we don't have one initially.
                    # but we do send a magic value that identifies ourselves so we know which PID is
                    # ours. This is hacky, yes.
                    # usually first connect
                    if self.player.net_state.pid == -1:
                        print("found a -1 pid, so thats probably us i guess")
                        if player_netstate.magic_value == self.player.net_state.magic_value:
                            self.player.net_state.pid = player_netstate.pid
                        else:
                            print(
                                f"CLIENT: Got a pid with -1 and not recognized magic value")

                    # ok, so we have the magic value (todo: this should really be the PID... it makes
                    # more sense for the clients to decide this themselves.

                    #update entity with authorative information from server,
                    # including ourselves.
                    for other_player in self.other_players.keys():
                        if player_netstate.pid == other_player:
                            other_players[other_player].netstate = player_netstate 

                    # This is the "us"-part
                    if pid == self.player.net_state.pid:
                        self.player.net_state = player_netstate
                        # server reconciliation:
                        # how are we doing relative to server?
                        # check if the server is behind us in terms of applying updates.
                        q = 0
                        #check all the inputs that we have sent to the server
                        while(q < len(self.pending_inputs)):
                            ev = self.pending_inputs[q]
                            #is last applied from server (msg[19])
                            #bigger than what we are ready to apply?
                            #just drop it. if not, we re-apply
                            #while waiting for server to update us
                            if(ev[7] <= player_netstate.last_applied_event_id):
                                #remove from pending inputs if the server has applied this already
                                self.pending_inputs.pop(q)
                            else:
                                print("Replaying old events due to missing server stuff")
                                self.player.react(ev[2], ev[3], ev[6], ev[8], self.gmap)
                                q+=1

                        continue

                    # first time we see this PID, so we create
                    # local "players" to keep (and draw) our opponents.
                    if pid not in self.other_players.keys():
                        new_player = Player()
                        self.other_players[pid] = new_player
                        self.update_player(new_player, player_netstate)
                        # todo: duplication...
                        self.scoreboard.add_player(new_player)
                        print(f"CLIENT: New player with pid {pid} connected!")
                    else:
                        self.update_player(self.other_players[pid], player_netstate)

            elif msg[0] == "player_disconnect":
                print(self.other_players)
                print("pid " + str(msg[1]) + " disconnected")
                if msg[1] in self.other_players:
                    self.scoreboard.remove_player(self.other_players[msg[1]])
                    self.other_players.pop(msg[1])

