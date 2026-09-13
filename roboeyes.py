import pygame
import sys
import random
import socket
import threading

# Constants for colors
BGCOLOR = (0, 0, 0)           # Black background
MAINCOLOR = (255, 255, 255)   # White drawings

# Mood Types
DEFAULT = 0
TIRED = 1
ANGRY = 2
HAPPY = 3
SAD = 4
LISTENING = 5

# --- Networking setup for real-time mood control ---
UDP_IP = "127.0.0.1"   # Only accept commands from this same machine
UDP_PORT = 5005

# Shared state between the listener thread and the main loop.
# We use a simple dict + lock so both threads can safely read/write it.
shared_state = {
    "mood": None,        # e.g. "HAPPY", "ANGRY", "TIRED", "SAD", "LISTENING", "DEFAULT"
    "action": None,      # e.g. "CONFUSED", "LAUGH"
    "quit": False,
}
state_lock = threading.Lock()

MOOD_MAP = {
    "DEFAULT": DEFAULT,
    "TIRED": TIRED,
    "ANGRY": ANGRY,
    "HAPPY": HAPPY,
    "SAD": SAD,
    "LISTENING": LISTENING,
}


def udp_listener():
    """
    Runs in a background thread. Listens for short text commands
    over UDP and stores the latest one in shared_state.

    The voice agent just needs to send one of these as bytes:
        "HAPPY", "ANGRY", "TIRED", "SAD", "LISTENING", "DEFAULT", "CONFUSED", "LAUGH", "QUIT"
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"[RoboEyes] Listening for mood commands on {UDP_IP}:{UDP_PORT}")

    while True:
        data, _addr = sock.recvfrom(1024)
        command = data.decode("utf-8").strip().upper()

        with state_lock:
            if command in MOOD_MAP:
                shared_state["mood"] = command
            elif command == "CONFUSED":
                shared_state["action"] = "CONFUSED"
            elif command == "LAUGH":
                shared_state["action"] = "LAUGH"
            elif command == "QUIT":
                shared_state["quit"] = True
            else:
                print(f"[RoboEyes] Unknown command received: {command}")


class RoboEyes:
    def __init__(self, draw_surface, width=900, height=400, frame_rate=50):
        self.surface = draw_surface
        self.screen_width = width
        self.screen_height = height
        self.frame_interval = 1000 / frame_rate
        self.fps_timer = pygame.time.get_ticks()

        self.tired = False
        self.angry = False
        self.happy = False
        self.sad = False
        self.listening = False
        self.curious = False
        self.cyclops = False
        self.eyeL_open = False
        self.eyeR_open = False

        self.space_between_default = 10
        self.space_between_current = self.space_between_default
        self.space_between_next = self.space_between_default

        self.eyeLwidth_default = 100
        self.eyeLheight_default = 100
        self.eyeLwidth_current = self.eyeLwidth_default
        self.eyeLheight_current = 1
        self.eyeLwidth_next = self.eyeLwidth_default
        self.eyeLheight_next = self.eyeLheight_default
        self.eyeLheight_offset = 0

        self.eyeLborder_radius_default = 20
        self.eyeLborder_radius_current = self.eyeLborder_radius_default
        self.eyeLborder_radius_next = self.eyeLborder_radius_default

        self.eyeRwidth_default = self.eyeLwidth_default
        self.eyeRheight_default = self.eyeLheight_default
        self.eyeRwidth_current = self.eyeRwidth_default
        self.eyeRheight_current = 1
        self.eyeRwidth_next = self.eyeRwidth_default
        self.eyeRheight_next = self.eyeRheight_default
        self.eyeRheight_offset = 0

        self.eyeRborder_radius_default = 20
        self.eyeRborder_radius_current = self.eyeRborder_radius_default
        self.eyeRborder_radius_next = self.eyeRborder_radius_default

        self.eyeLx_default = (self.screen_width - (self.eyeLwidth_default + self.space_between_default + self.eyeRwidth_default)) // 2
        self.eyeLy_default = (self.screen_height - self.eyeLheight_default) // 2
        self.eyeLx = self.eyeLx_default
        self.eyeLy = self.eyeLy_default
        self.eyeLx_next = self.eyeLx
        self.eyeLy_next = self.eyeLy

        self.eyeRx_default = self.eyeLx + self.eyeLwidth_current + self.space_between_default
        self.eyeRy_default = self.eyeLy
        self.eyeRx = self.eyeRx_default
        self.eyeRy = self.eyeRy_default
        self.eyeRx_next = self.eyeRx
        self.eyeRy_next = self.eyeRy

        self.eyelids_height_max = self.eyeLheight_default // 2
        self.eyelids_tired_height = 0
        self.eyelids_tired_height_next = self.eyelids_tired_height
        self.eyelids_angry_height = 0
        self.eyelids_angry_height_next = self.eyelids_angry_height
        self.eyelids_sad_height = 0
        self.eyelids_sad_height_next = self.eyelids_sad_height
        self.eyelids_happy_bottom_offset_max = (self.eyeLheight_default // 2) + 6
        self.eyelids_happy_bottom_offset = 0
        self.eyelids_happy_bottom_offset_next = 0

        # How much bigger the eyes get while actively "listening"
        self.listening_boost_max = 45
        self.listening_boost = 0
        self.listening_boost_next = 0

        self.hFlicker = False
        self.hFlicker_alternate = False
        self.hFlicker_amplitude = 4

        self.vFlicker = False
        self.vFlicker_alternate = False
        self.vFlicker_amplitude = 20

        self.autoblinker = False
        self.blink_interval = 2000
        self.blink_interval_variation = 4000
        self.blink_timer = pygame.time.get_ticks()

        self.idle = False
        self.idle_interval = 5000
        self.idle_interval_variation = 5000
        self.idle_animation_timer = pygame.time.get_ticks()

        self.confused = False
        self.confused_animation_timer = 0
        self.confused_animation_duration = 500
        self.confused_toggle = True

        self.laugh = False
        self.laugh_animation_timer = 0
        self.laugh_animation_duration = 500
        self.laugh_toggle = True

    def begin(self):
        self.clear_display()
        self.eyeLheight_current = 1
        self.eyeRheight_current = 1

    def update(self):
        current_time = pygame.time.get_ticks()
        if current_time - self.fps_timer >= self.frame_interval:
            self.drawEyes()
            self.fps_timer = current_time

    def setFramerate(self, fps):
        self.frame_interval = 1000 / fps

    def setWidth(self, leftEye, rightEye):
        self.eyeLwidth_next = leftEye
        self.eyeRwidth_next = rightEye
        self.eyeLwidth_default = leftEye
        self.eyeRwidth_default = rightEye

    def setHeight(self, leftEye, rightEye):
        self.eyeLheight_next = leftEye
        self.eyeRheight_next = rightEye
        self.eyeLheight_default = leftEye
        self.eyeRheight_default = rightEye

    def setBorderradius(self, leftEye, rightEye):
        self.eyeLborder_radius_next = leftEye
        self.eyeRborder_radius_next = rightEye
        self.eyeLborder_radius_default = leftEye
        self.eyeRborder_radius_default = rightEye

    def setSpacebetween(self, space):
        self.space_between_next = space
        self.space_between_default = space

    def setMood(self, mood):
        # Reset all mood flags first, then set the one that applies.
        self.tired = False
        self.angry = False
        self.happy = False
        self.sad = False
        self.listening = False
        self.listening_boost_next = 0

        if mood == TIRED:
            self.tired = True
        elif mood == ANGRY:
            self.angry = True
        elif mood == HAPPY:
            self.happy = True
        elif mood == SAD:
            self.sad = True
        elif mood == LISTENING:
            self.listening = True
            self.listening_boost_next = self.listening_boost_max
        # else: DEFAULT - everything already reset above

    def setAutoblinker(self, active, interval=2, variation=4):
        self.autoblinker = active
        self.blink_interval = interval * 1000
        self.blink_interval_variation = variation * 1000

    def setIdleMode(self, active, interval=5, variation=5):
        self.idle = active
        self.idle_interval = interval * 1000
        self.idle_interval_variation = variation * 1000

    def setCuriosity(self, curious_bit):
        self.curious = curious_bit

    def setCyclops(self, cyclops_bit):
        self.cyclops = cyclops_bit

    def setHFlicker(self, flicker_bit, amplitude=4):
        self.hFlicker = flicker_bit
        self.hFlicker_amplitude = amplitude

    def setVFlicker(self, flicker_bit, amplitude=20):
        self.vFlicker = flicker_bit
        self.vFlicker_amplitude = amplitude

    def getScreenConstraint_X(self):
        return self.screen_width - self.eyeLwidth_current - self.space_between_current - self.eyeRwidth_current

    def getScreenConstraint_Y(self):
        return self.screen_height - self.eyeLheight_default

    def close(self, left=True, right=True):
        if left:
            self.eyeLheight_next = 1
            self.eyeL_open = False
        if right:
            self.eyeRheight_next = 1
            self.eyeR_open = False

    def open_eyes(self, left=True, right=True):
        if left:
            self.eyeL_open = True
        if right:
            self.eyeR_open = True

    def blink(self, left=True, right=True):
        self.close(left, right)
        self.open_eyes(left, right)

    def anim_confused(self):
        self.confused = True

    def anim_laugh(self):
        self.laugh = True

    def drawEyes(self):
        current_time = pygame.time.get_ticks()

        # Smoothly ease the listening size boost in/out, same pattern as
        # other "current/next" smoothing used throughout this class.
        self.listening_boost = (self.listening_boost + self.listening_boost_next) // 2

        if self.curious:
            if self.eyeLx_next <= 20:
                self.eyeLheight_offset = 16
            elif self.eyeLx_next >= (self.getScreenConstraint_X() - 20) and self.cyclops:
                self.eyeLheight_offset = 16
            else:
                self.eyeLheight_offset = 0

            if self.eyeRx_next >= self.screen_width - self.eyeRwidth_current - 20:
                self.eyeRheight_offset = 16
            else:
                self.eyeRheight_offset = 0
        else:
            self.eyeLheight_offset = 0
            self.eyeRheight_offset = 0

        # Listening adds extra height on top of whatever curiosity offset
        # is already applying, giving a wide, alert-eyed look.
        total_left_offset = self.eyeLheight_offset + self.listening_boost
        total_right_offset = self.eyeRheight_offset + self.listening_boost

        self.eyeLheight_current = (self.eyeLheight_current + self.eyeLheight_next + total_left_offset) // 2
        self.eyeLy += ((self.eyeLheight_default - self.eyeLheight_current) // 2)
        self.eyeLy -= total_left_offset // 2

        self.eyeRheight_current = (self.eyeRheight_current + self.eyeRheight_next + total_right_offset) // 2
        self.eyeRy += ((self.eyeRheight_default - self.eyeRheight_current) // 2)
        self.eyeRy -= total_right_offset // 2

        if self.eyeL_open:
            if self.eyeLheight_current <= 1 + total_left_offset:
                self.eyeLheight_next = self.eyeLheight_default

        if self.eyeR_open:
            if self.eyeRheight_current <= 1 + total_right_offset:
                self.eyeRheight_next = self.eyeRheight_default

        self.eyeLwidth_current = (self.eyeLwidth_current + self.eyeLwidth_next + self.listening_boost) // 2
        self.eyeRwidth_current = (self.eyeRwidth_current + self.eyeRwidth_next + self.listening_boost) // 2
        self.eyeLx -= self.listening_boost // 2
        self.eyeRx -= self.listening_boost // 2
        self.space_between_current = (self.space_between_current + self.space_between_next) // 2

        self.eyeLx = (self.eyeLx + self.eyeLx_next) // 2
        self.eyeLy = (self.eyeLy + self.eyeLy_next) // 2

        self.eyeRx_next = self.eyeLx_next + self.eyeLwidth_current + self.space_between_current
        self.eyeRy_next = self.eyeLy_next
        self.eyeRx = (self.eyeRx + self.eyeRx_next) // 2
        self.eyeRy = (self.eyeRy + self.eyeRy_next) // 2

        self.eyeLborder_radius_current = (self.eyeLborder_radius_current + self.eyeLborder_radius_next) // 2
        self.eyeRborder_radius_current = (self.eyeRborder_radius_current + self.eyeRborder_radius_next) // 2

        if self.autoblinker and (current_time >= self.blink_timer):
            self.blink()
            variation = random.randint(0, self.blink_interval_variation)
            self.blink_timer = current_time + self.blink_interval + variation

        if self.laugh:
            if self.laugh_toggle:
                self.setVFlicker(True, 10)
                self.laugh_animation_timer = current_time
                self.laugh_toggle = False
            elif current_time >= self.laugh_animation_timer + self.laugh_animation_duration:
                self.setVFlicker(False, 0)
                self.laugh_toggle = True
                self.laugh = False

        if self.confused:
            if self.confused_toggle:
                self.setHFlicker(True, 40)
                self.confused_animation_timer = current_time
                self.confused_toggle = False
            elif current_time >= self.confused_animation_timer + self.confused_animation_duration:
                self.setHFlicker(False, 0)
                self.confused_toggle = True
                self.confused = False

        if self.idle and (current_time >= self.idle_animation_timer):
            self.eyeLx_next = random.randint(0, self.getScreenConstraint_X())
            self.eyeLy_next = random.randint(0, self.getScreenConstraint_Y())
            variation = random.randint(0, self.idle_interval_variation)
            self.idle_animation_timer = current_time + self.idle_interval + variation

        if self.hFlicker:
            if self.hFlicker_alternate:
                self.eyeLx += self.hFlicker_amplitude
                self.eyeRx += self.hFlicker_amplitude
            else:
                self.eyeLx -= self.hFlicker_amplitude
                self.eyeRx -= self.hFlicker_amplitude
            self.hFlicker_alternate = not self.hFlicker_alternate

        if self.vFlicker:
            if self.vFlicker_alternate:
                self.eyeLy += self.vFlicker_amplitude
                self.eyeRy += self.vFlicker_amplitude
            else:
                self.eyeLy -= self.vFlicker_amplitude
                self.eyeRy -= self.vFlicker_amplitude
            self.vFlicker_alternate = not self.vFlicker_alternate

        if self.cyclops:
            self.eyeRwidth_current = 0
            self.eyeRheight_current = 0
            self.space_between_current = 0

        self.clear_display()

        self.draw_eye(self.eyeLx, self.eyeLy, self.eyeLwidth_current, self.eyeLheight_current,
                     self.eyeLborder_radius_current, MAINCOLOR)
        if not self.cyclops:
            self.draw_eye(self.eyeRx, self.eyeRy, self.eyeRwidth_current, self.eyeRheight_current,
                         self.eyeRborder_radius_current, MAINCOLOR)

        if self.tired:
            self.eyelids_tired_height_next = self.eyeLheight_current // 2
            self.eyelids_angry_height_next = 0
            self.eyelids_sad_height_next = 0
        elif self.angry:
            self.eyelids_angry_height_next = self.eyeLheight_current // 2
            self.eyelids_tired_height_next = 0
            self.eyelids_sad_height_next = 0
        elif self.sad:
            self.eyelids_sad_height_next = self.eyeLheight_current // 2
            self.eyelids_tired_height_next = 0
            self.eyelids_angry_height_next = 0
        else:
            self.eyelids_tired_height_next = 0
            self.eyelids_angry_height_next = 0
            self.eyelids_sad_height_next = 0

        if self.happy:
            self.eyelids_happy_bottom_offset_next = self.eyeLheight_current // 2
        else:
            self.eyelids_happy_bottom_offset_next = 0

        # --- Tired eyelids ---
        self.eyelids_tired_height = (self.eyelids_tired_height + self.eyelids_tired_height_next) // 2
        if not self.cyclops:
            points_left = [
                (self.eyeLx, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy - 1),
                (self.eyeLx, self.eyeLy + self.eyelids_tired_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_left)

            points_right = [
                (self.eyeRx, self.eyeRy - 1),
                (self.eyeRx + self.eyeRwidth_current, self.eyeRy - 1),
                (self.eyeRx + self.eyeRwidth_current, self.eyeRy + self.eyelids_tired_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_right)
        else:
            half_width = self.eyeLwidth_current // 2
            points_left = [
                (self.eyeLx, self.eyeLy - 1),
                (self.eyeLx + half_width, self.eyeLy - 1),
                (self.eyeLx, self.eyeLy + self.eyelids_tired_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_left)

            points_right = [
                (self.eyeLx + half_width, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy + self.eyelids_tired_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_right)

        # --- Angry eyelids (inner corners down - "furrowed brow") ---
        self.eyelids_angry_height = (self.eyelids_angry_height + self.eyelids_angry_height_next) // 2
        if not self.cyclops:
            points_left = [
                (self.eyeLx, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy + self.eyelids_angry_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_left)

            points_right = [
                (self.eyeRx, self.eyeRy - 1),
                (self.eyeRx + self.eyeRwidth_current, self.eyeRy - 1),
                (self.eyeRx, self.eyeRy + self.eyelids_angry_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_right)
        else:
            half_width = self.eyeLwidth_current // 2
            points_left = [
                (self.eyeLx, self.eyeLy - 1),
                (self.eyeLx + half_width, self.eyeLy - 1),
                (self.eyeLx + half_width, self.eyeLy + self.eyelids_angry_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_left)

            points_right = [
                (self.eyeLx + half_width, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy - 1),
                (self.eyeLx + half_width, self.eyeLy + self.eyelids_angry_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_right)

        # --- Sad eyelids (mirror of angry - outer corners down, "puppy eyes") ---
        self.eyelids_sad_height = (self.eyelids_sad_height + self.eyelids_sad_height_next) // 2
        if not self.cyclops:
            points_left = [
                (self.eyeLx, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy - 1),
                (self.eyeLx, self.eyeLy + self.eyelids_sad_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_left)

            points_right = [
                (self.eyeRx, self.eyeRy - 1),
                (self.eyeRx + self.eyeRwidth_current, self.eyeRy - 1),
                (self.eyeRx + self.eyeRwidth_current, self.eyeRy + self.eyelids_sad_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_right)
        else:
            half_width = self.eyeLwidth_current // 2
            points_left = [
                (self.eyeLx, self.eyeLy - 1),
                (self.eyeLx + half_width, self.eyeLy - 1),
                (self.eyeLx, self.eyeLy + self.eyelids_sad_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_left)

            points_right = [
                (self.eyeLx + half_width, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy - 1),
                (self.eyeLx + self.eyeLwidth_current, self.eyeLy + self.eyelids_sad_height - 1)
            ]
            pygame.draw.polygon(self.surface, BGCOLOR, points_right)

        # --- Happy eyelids (rising from the bottom) ---
        self.eyelids_happy_bottom_offset = (self.eyelids_happy_bottom_offset + self.eyelids_happy_bottom_offset_next) // 2
        pygame.draw.rect(self.surface, BGCOLOR,
                         (self.eyeLx - 2, (self.eyeLy + self.eyeLheight_current) - self.eyelids_happy_bottom_offset + 2,
                          self.eyeLwidth_current + 4, self.eyeLheight_default))
        if not self.cyclops:
            pygame.draw.rect(self.surface, BGCOLOR,
                             (self.eyeRx - 2, (self.eyeRy + self.eyeRheight_current) - self.eyelids_happy_bottom_offset + 2,
                              self.eyeRwidth_current + 4, self.eyeRheight_default))

    def draw_eye(self, x, y, width, height, border_radius, color):
        eye_rect = pygame.Rect(x, y, width, height)
        if border_radius > 0:
            pygame.draw.rect(self.surface, color, eye_rect, border_radius=border_radius)
        else:
            pygame.draw.rect(self.surface, color, eye_rect)

    def clear_display(self):
        self.surface.fill(BGCOLOR)


def main():
    # pygame.init()
    pygame.display.init()
    pygame.font.init()

    # Fullscreen, auto-detect resolution
    window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    screen_width, screen_height = window.get_size()
    pygame.display.set_caption("RoboEyes Simulation")

    draw_width = screen_width
    draw_height = screen_height
    draw_surface = pygame.Surface((draw_width, draw_height))
    draw_surface.fill(BGCOLOR)

    robo_eyes = RoboEyes(draw_surface, width=draw_width, height=draw_height, frame_rate=50)
    robo_eyes.begin()

    robo_eyes.setMood(DEFAULT)
    robo_eyes.setAutoblinker(True, interval=2, variation=3)
    robo_eyes.setIdleMode(True, interval=5, variation=5)
    robo_eyes.setCuriosity(True)

    # Start the background thread that listens for commands from the voice agent
    listener_thread = threading.Thread(target=udp_listener, daemon=True)
    listener_thread.start()

    clock = pygame.time.Clock()

    mood_reset_delay = 5000  # milliseconds (5 seconds)
    mood_reset_timer = None

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:
                    robo_eyes.setMood(TIRED)
                elif event.key == pygame.K_2:
                    robo_eyes.setMood(ANGRY)
                elif event.key == pygame.K_3:
                    robo_eyes.setMood(HAPPY)
                elif event.key == pygame.K_4:
                    robo_eyes.setMood(SAD)
                elif event.key == pygame.K_5:
                    robo_eyes.setMood(LISTENING)
                elif event.key == pygame.K_0:
                    robo_eyes.setMood(DEFAULT)
                elif event.key == pygame.K_c:
                    robo_eyes.anim_confused()
                elif event.key == pygame.K_l:
                    robo_eyes.anim_laugh()
                elif event.key == pygame.K_q or event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()

        # Check if the voice agent sent us anything new
        with state_lock:
            if shared_state["mood"] is not None:
                robo_eyes.setMood(MOOD_MAP[shared_state["mood"]])
                if shared_state["mood"] != "DEFAULT":
                    mood_reset_timer = pygame.time.get_ticks() + mood_reset_delay
                else:
                    mood_reset_timer = None
                shared_state["mood"] = None

            if shared_state["action"] == "CONFUSED":
                robo_eyes.anim_confused()
                shared_state["action"] = None
            elif shared_state["action"] == "LAUGH":
                robo_eyes.anim_laugh()
                shared_state["action"] = None

            if shared_state["quit"]:
                pygame.quit()
                sys.exit()
        # if the mood reset timer has expired, reset to DEFAULT
        if mood_reset_timer is not None and pygame.time.get_ticks() >= mood_reset_timer:
            robo_eyes.setMood(DEFAULT)
            mood_reset_timer = None

        robo_eyes.update()

        rect = draw_surface.get_rect(center=window.get_rect().center)
        window.fill(BGCOLOR)
        window.blit(draw_surface, rect)

        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    main()