from collections import deque
import pickle
import errno
import random
import pygame
import pygame.locals
import pygame.image
import pygame.time
import glob
import numpy as np

import enum
from PIL import Image

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
            return self.frames[self.current_frame % num_frames]
        else:
            retval = self.frames[self.current_frame % num_frames]
            self.current_frame += 1  # hopefully usually 1..
        return retval

    def load_frames_sheet(self, shape, path, scale=1.0):
        # shape=(8,8)
        srf = pygame.image.load(path)  # .convert_alpha()
        srf_size = srf.get_size()
        if scale > 1.0:
            srf = pygame.transform.scale(
                srf, (int(srf_size[0] * scale), int(srf_size[1] * scale)))

        srf_size = srf.get_size()
        frame_w = srf_size[0]/shape[0]
        frame_h = srf_size[1]/shape[1]
        self.frame_width = frame_w
        self.frame_height = frame_h

        for fh in range(shape[1]):
            for fw in range(shape[0]):
                source_rect = pygame.Rect(
                    (frame_w * fw, frame_h * fh, frame_w, frame_h))
                img = pygame.Surface(source_rect.size, pygame.SRCALPHA)
                img.blit(srf, (0, 0), source_rect)
                self.frames.append(img)
                # print("Added frame", source_rect)


class PlayerState(enum.Enum):
    active = 0
    dead = 1


class GameState(enum.Enum):
    lobby = 0
    running = 1

class GameMap():
    def __init__(self, mapfile=None, size=(2000, 1000), server=False):
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
            self.map = pygame.image.load(mapfile).convert()  # .convert_alpha()

        self.current_visible_surface = None

        self.tile_width = 1
        self.tile_height = 1

        self.spawnpoints = [[0, 0],
                            [self.size[0]-16, self.size[1] - 1000],
                            [self.size[0]/2, self.size[1]/2]]

    def blit_visible_surface(self, camera_pos, viewport, zoom=1.0):
        # the map is represented in genmap[y][x].
        # the camera moves in pixel-land, but we are interested in
        # in figuring out which map tiles to draw.

        # camera is center, so we draw each side. remember we go top->bottom, left-right.
        visible_top = camera_pos[1] - viewport.get_height()/2.
        # 600 - 1024/2 = 600 - 512 = 88.
        visible_left = camera_pos[0] - viewport.get_width()/2.

        # view_rect is in tiles.
        v_left = max(0, min(visible_left, self.size[0]-viewport.get_width()))
        v_top = max(0, min(visible_top, self.size[1]-viewport.get_height()))

        v_width = min(viewport.get_width(), self.size[0])
        v_height = min(viewport.get_height(), self.size[1])

        # view rect is in global map px coordinates. it is the 'visible rect'.
        view_rect = pygame.Rect(v_left, v_top, v_width, v_height)

        self.current_visible_surface = self.map.subsurface(view_rect)

        viewport.blit(self.current_visible_surface, (0, 0))
        return (view_rect)

# just a datastructure


class Bullet():
    def __init__(self, pos=None, velocity=None):
        self.velocity = velocity
        self.rect = pygame.Rect(pos, (8, 8))
        self.color = pygame.Color(255, 0, 0)
        self.type = 0
        # self.img = pygame.Surface((8,8))
        # self.img.fill(self.color)

class PlayerNetState():
    def __init__(self):
        self.pid = -1

        self.movespeed = 800
        self.jumpspeed = 1500
        self.gravity = 1000

        self.health = 5

        self.velocity = [0., 0.]
        self.grounded = False
        self.facing_left = False
        
        #position
        self.rect = pygame.Rect((0,0), (16, 16))

        # these are things that are fired and needs updating when time ticks.
        self.bullets = []
        self.name = "Jumbo"
        self.score = 0
        self.ready = False
 
        self.posx = 0
        self.posy = 0

        self.holding_up = False
        self.holding_down = False

        self.spawnpoint = 0
        self.cooldown = 0
        self.status = PlayerState.active
        
        self.hitters = []

        self.last_applied_event_id = 0

        #randomize
        self.color = pygame.Color(255, 0, 0)
        self.magic_value = None
    

class Player(pygame.sprite.Sprite):
    def __init__(self, frames=None, client=False):
        super().__init__()

        self.client = client
        self.cliaddr = None

        self.net_state = PlayerNetState()

        # Stuff to do with rendering.
        self.img = pygame.Surface((16, 16))
        self.img.fill(self.net_state.color)

        self.hit_img = pygame.Surface((16, 16))
        self.hit_img.fill((255, 255, 255))

        self.death_anim = Animation(fps=30)
        self.death_anim.load_frames_sheet(
            (8, 8), 'particlefx_12.png', scale=3.0)

        # This stores the updates from the server when they arrive; 
        # and we'll interpolate "up to" this point in time when
        # rendering positions of enemies.
        self.position_buffer = deque()


    def update_color(self, col):
        self.color = col
        self.img.fill(self.color)

    def react(self, event_type, event_key, keystate, dt, mappy):
        if event_type == pygame.KEYDOWN:
            if event_key == pygame.K_a:
                self.net_state.facing_left = True
                self.net_state.velocity[0] = -self.net_state.movespeed
            if event_key == pygame.K_d:
                self.net_state.facing_left = False
                self.net_state.velocity[0] = self.net_state.movespeed
            if event_key == pygame.K_j:
                if self.net_state.grounded:
                    self.net_state.velocity[1] = -self.net_state.movespeed
            if event_key == pygame.K_w:
                self.net_state.holding_up = True
            if event_key == pygame.K_s:
                self.net_state.holding_down = True

            if event_key == pygame.K_k:
                # fire weapon
                vel = []
                # holding up
                if self.net_state.holding_up:
                    vel = [0, -self.net_state.jumpspeed]
                # down
                elif self.net_state.holding_down:
                    vel = [0, self.net_state.jumpspeed]
                else:
                    if self.net_state.facing_left:
                        vel = [-self.net_state.jumpspeed, 0]
                    else:
                        vel = [self.net_state.jumpspeed, 0]
                self.net_state.bullets.append(Bullet(pos=self.net_state.rect.center, velocity=vel))
                # print(f'added bullet at {self.net_state.rect.center}, speed {vel}')

        if event_type == pygame.KEYUP:
            # pressed keys
            if event_key == pygame.K_a and self.net_state.velocity[0] <= 0:
                if keystate[pygame.K_d]:
                    self.net_state.facing_left = False
                    self.net_state.velocity[0] = self.net_state.movespeed
                else:
                    self.net_state.velocity[0] = 0
            if event_key == pygame.K_d and self.net_state.velocity[0] > 0:
                if keystate[pygame.K_a]:
                    self.net_state.facing_left = True
                    self.net_state.velocity[0] = -self.net_state.movespeed
                else:
                    self.net_state.velocity[0] = 0
            if event_key == pygame.K_j and self.net_state.velocity[0] < 0:
                self.net_state.velocity[1] = 0
            if event_key == pygame.K_w:
                self.net_state.holding_up = False
            if event_key == pygame.K_s:
                self.net_state.holding_down = False

        self.net_state.grounded = False

        delta_distance_x = self.net_state.velocity[0] * dt
        self.net_state.posx += delta_distance_x
        self.net_state.rect.x = int(max(0, min(mappy.size[0]-16, self.net_state.posx)))

        # px = pygame.PixelArray(mappy.map)
        px = mappy.pixels

        raylen = 30  # int(abs(delta_distance_y)) + 1

        # collision_value = mappy.map.map_rgb(255,0,0)  #what?
        collision_value = [255, 0, 0]

        # bottom collision, iterate all pixels and check for match.
        if self.net_state.velocity[1] >= 0:  # we are falling, positive is down.
            for rpixl in range(self.net_state.rect.bottom, min(mappy.size[1], self.net_state.rect.bottom + raylen)):
                if (px[self.net_state.rect.centerx][rpixl] == collision_value).all():
                    self.net_state.rect.bottom = rpixl  # set the y position to the grounded coordinate
                    # self.posy = self.net_state.rect.bottom
                    self.net_state.velocity[1] = 0
                    self.net_state.grounded = True
                    break

        delta_distance_y = 0.0
        # if we are not grounded,
        if not self.net_state.grounded:
            # gravity, but why is this fucked?
            self.net_state.velocity[1] += self.net_state.gravity * dt
            delta_distance_y = self.net_state.velocity[1] * dt
            self.net_state.posy += delta_distance_y
            self.net_state.rect.y = int(max(0, min(mappy.size[1]-16, self.net_state.posy)))

        # print(f"updated: {self.net_state.velocity[0]}, dt {dt}, delta {delta_distance_x} newpos {self.posx} newrect {self.net_state.rect.x}")
        # print(f"updated: {self.net_state.velocity[1]}, dt {dt}, delta {delta_distance_y} newpos {self.posy} newrect {self.net_state.rect.y}")

        # update bullets
        for b in self.net_state.bullets:
            b.rect.x += dt * b.velocity[0]
            b.rect.y += dt * b.velocity[1]

        to_remove = []
        for idx, (timeleft, hitter) in enumerate(self.net_state.hitters):
            if timeleft <= 0.0:
                to_remove.append(idx)
            else:
                self.net_state.hitters[idx][0] = max(0.0, timeleft - dt)
        for idx in set(to_remove):
            self.net_state.hitters.pop(idx)

        # if we died
        if self.net_state.status == PlayerState.dead:
            if self.net_state.cooldown == 0:
                self.net_state.status = PlayerState.active
                sp = random.randrange(0, len(mappy.spawnpoints))
                self.net_state.rect.x = mappy.spawnpoints[sp][0]
                self.net_state.rect.y = mappy.spawnpoints[sp][1]
                self.net_state.posx = self.net_state.rect.x
                self.net_state.posy = self.net_state.rect.y

    def bullet_collisions(self, mappy, dt):
        # px = pygame.PixelArray(mappy.map)
        px = mappy.pixels
        for b in self.net_state.bullets:
            if b.rect.right > mappy.size[0]:
                self.net_state.bullets.remove(b)
                continue
            if b.rect.left < 0:
                self.net_state.bullets.remove(b)
                continue
            if b.rect.top > mappy.size[1]:
                self.net_state.bullets.remove(b)
                continue
            if b.rect.bottom < 0:
                self.net_state.bullets.remove(b)
                continue

            delta_distance_y = dt * b.velocity[1]
            raylen = int(abs(delta_distance_y)) + 1

            collision_value = [255, 0, 0]
            # bottom collision, iterate all pixels and check for match.
            if b.velocity[1] > 0:  # bullets going down
                if self.net_state.grounded:
                    self.net_state.bullets.remove(b)
                    continue
                for rpixl in range(b.rect.bottom, min(mappy.size[1], b.rect.bottom + raylen)):
                    if (px[b.rect.centerx][rpixl] == collision_value).all():
                        self.net_state.bullets.remove(b)
                        break
            # bullets going up
            elif b.velocity[1] < 0:
                # print(b.rect.top - raylen, b.rect.top)
                for rpixl in range(max(0, b.rect.top - raylen), b.rect.top):
                    if (px[b.rect.centerx][rpixl] == collision_value).all():
                        self.net_state.bullets.remove(b)
                        break

        return


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
    # while bytes_rcv < MSGLEN: #header
    try:
        chunk, server = socket.recvfrom(MSGLEN)
        chunks.append(chunk)
    except OSError as e:
        if e.errno == errno.EWOULDBLOCK:
            return None, None
        if chunk == b'':
            print(
                "WARNING: SOCKET BROKEN. ASSUMING ALL IS SHIT AND REMOVING THIS SOCKET.")

    msg = pickle.loads(b''.join(chunks))
    # print("received message ", msg)
    return msg, server


class TextInputBox():
    def __init__(self, leadtext="", position=(0, 0), font_color=(0, 0, 0)):
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
        letter_render = self.font.render(
            self.leadtext + self.entered_text, True, self.font_color)
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
    def __init__(self, lines=[], color=pygame.Color('black'), font='inconsolata.ttf', fontsize=20, bgcolor=(50, 500, 100, 255)):
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
        # re-render and return a new surface.
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
        # fill the surface with black and fully visible alpha channel.
        # blend_mult will multiply pixels and shift 8 right (div by 256)
        self.textsurface.fill(self.bgcolor)
        for rownum, line_surface in enumerate(row_surf):
            self.textsurface.blit(
                line_surface, (0, max_height * rownum), special_flags=pygame.BLEND_RGBA_MULT)

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
            return pygame.Surface((1, 1))
        else:
            return self.scoresurface

    def update_scoreboard_surface(self):
        row_height = 22
        row_width = 400

        # just to get the size of the object to be... this is shit and ou know it.
        row = TextMessage("Kills: ",
                          (0, 0), 0, fontsize=20)
        surfdims = row.get_surface(0).get_size()

        surfsize = (row_width, surfdims[1] * len(self.players))
        final_surface = pygame.Surface(surfsize, pygame.SRCALPHA)
        final_surface.fill((255, 255, 255, 255))

        rownum = 0
        for p in reversed(sorted(self.players, key=lambda x: x.net_state.score)):
            row = TextMessage(p.net_state.name + " Kills: " + str(p.net_state.score),
                              (0, 0), 0, fontsize=20)
            final_surface.blit(row.get_surface(
                0), (0, surfdims[1] * rownum), special_flags=pygame.BLEND_RGBA_MULT)
            final_surface.fill((0, 0, 0, 0), rect=pygame.Rect(row.get_surface(0).get_width(),
                                                              rownum *
                                                              surfdims[1],
                                                              row_width -
                                                              row.get_surface(
                                                                  0).get_width(),
                                                              surfdims[1]),
                               special_flags=pygame.BLEND_RGBA_MULT
                               )

            rownum += 1

        self.scoresurface = final_surface

