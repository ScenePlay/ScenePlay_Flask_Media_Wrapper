import time
import board
import neopixel
import json
import json
import random
import math
import sqlite3
import os
#Runs as a stand alone file. 
database = 'ScenePlay.db'
databaseDir = os.path.dirname(os.path.realpath(__file__)) + '/' + database

num_pixels = 0
pixel_pin = None
_brightness = 0


def getLEDOutPIN():
    conn = sqlite3.connect(databaseDir)
    c = conn.cursor()
    c.execute("SELECT * FROM tblLEDConfig where active = 1")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data


LedPins = getLEDOutPIN()

if LedPins is not None:
    for item in LedPins:
        if item[1] == 21:
            pixel_pin = board.D21
            num_pixels = item[2]
            _brightness = item[3]
        elif item[1] == 18:
            pixel_pin = board.D18
            num_pixels = item[2]
            _brightness = item[3]


def get_LEDJSON():
    conn = sqlite3.connect(databaseDir)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT ledJSON FROM tblLED")
    data = c.fetchall()
    c.execute("DELETE FROM tblLED")
    conn.commit()
    c.close()
    conn.close()
    for r in data:
        row = r[0]
    return row




#print(pixel_pin, num_pixels)

# Configuration

ORDER = neopixel.GRB
# Create NeoPixel object
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=_brightness, auto_write=False, pixel_order=ORDER)

def solid_color(color):
    pixels.fill(color)
    pixels.show()

def color_wipe(color, wait_ms,direction=1):
    if(direction > 0):
        start = 0
        end = num_pixels
    else:
        start = num_pixels-1
        end = 0
    for i in range(start,end,direction):
        pixels[i] = color
        pixels.show()
        time.sleep(wait_ms / 1000.0)

def rainbow_cycle(iterations=5):
    for j in range(256 * iterations):
        for i in range(num_pixels):
            pixel_index = (i * 256 // num_pixels) + j
            pixels[i] = wheel(pixel_index & 255)
        pixels.show()

def wheel(pos):
    if pos < 85:
        return (pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return (255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return (0, pos * 3, 255 - pos * 3)
    
def beam(color, wait_ms, iterations,direction):
    if(direction > 0):
        start = 0
        end = num_pixels
    else:
        start = num_pixels-1
        end = 0
        
    for j in range(iterations):
        for i in range(start,end,direction):
            pixels[i] = [color[0], color[1], color[2]]
            pixels.show()
            pixels.fill([0, 0, 0])
            time.sleep(wait_ms/1000)
        pixels.fill([0, 0, 0])
        pixels.show()


def colorRand(color_component, difference):
    """
    Generates a random color value within a given range of a base color component.

    Args:
        color_component (int): The base R, G, or B value (0-255).
        difference (int): The max random difference to apply. Clamped at 100.

    Returns:
        int: A new random color component between 0 and 255.
    """
    # Clamp the difference to a maximum of 100 to keep colors from varying too wildly
    if difference > 100:
        difference = 100

    # To prevent random.randint from getting an invalid range (e.g., randint(-10, 30)),
    # we shift the center color away from the boundary.
    if color_component < difference:
        color_component = difference
    if color_component > 255 - difference:
        color_component = 255 - difference
        
    return random.randint(color_component - difference, color_component + difference)

def sparkle(color_center, cdiff, wait_ms, iterations):
    """
    Fills the strip with a color and then permanently changes random pixels
    to a variation of that color, one by one.
    Also, gently pulses the brightness of the entire strip.
    """
    pixels.fill(color_center)
    pixels.show()

    brightFlag = False
    for _ in range(iterations):
        # Choose a single random pixel to change
        pixel_to_sparkle = random.randint(0, num_pixels - 1)

        # Generate a new random color for that pixel
        sparkle_color = (
            colorRand(color_center[0], cdiff[0]),
            colorRand(color_center[1], cdiff[1]),
            colorRand(color_center[2], cdiff[2])
        )
        pixels[pixel_to_sparkle] = sparkle_color

        # Oscillate the global brightness
        if brightFlag:
            pixels.brightness = max(0, pixels.brightness - 0.008) # Prevent negative brightness
            brightFlag = False
        else:
            pixels.brightness = min(1.0, pixels.brightness + 0.008) # Clamp brightness at 1.0
            brightFlag = True

        pixels.show()
        time.sleep(random.randint(1, wait_ms) / 1000.0)



def rainbow_rotate_adjust(c):
    for i in range(3):
        if c[1][i] == True:
            if c[0][i] >= 254:
                c[1][i] =  False
            else:
                c[0][i] +=1
        else:
            if c[0][i] <= 1:
                c[1][i] = True
            else:
                c[0][i] -=1
    return(c)

def rainbow_rotate(wait_ms=1, iterations=10):
    bl_color = [True,True,True]
    color = [0,0,0]
    c = [color,bl_color]
    for j in range(256*iterations):
        c[1][0] = False if j&256 == 0 else True
        c[1][1] = False if j&256*2 == 0 else True
        c[1][2] = True if j&256*3 == 0 else False
        c = rainbow_rotate_adjust(c)
        #print(f"{j} {c}")
        pixels.fill([c[0][0], c[0][1], c[0][2]])  # Vary the red channel
        pixels.show()
        time.sleep(wait_ms/1000)


def eye_look(color,wait_ms,iterations):
    i = eye(color,num_pixels)
    j = eye(color,num_pixels)
    
    for q in range(iterations):
        i.move(random.randint(0,num_pixels-1),wait_ms)
        j.move(random.randint(0,num_pixels-1),wait_ms)

    
class eye:
    def __init__(self, colorPre,p_ct) -> None:
        color = [0,0,0]
        color = [colorPre[0],colorPre[1],colorPre[2]]
        self.__BaseColor = color
        self.__I = []
        self.p_ct = p_ct - 1
        self.__createEye()
        pass
    
    class eyeMatter:
        def __init__(self,location,color) -> None:
            self.color = color
            self.location = location
            self.futureL = 0
            pass
        
    def __createEye(self):
        eyeLength = 10
        eyeBright = []
        
        for i in range(0,eyeLength//2,1):
            if i == 0:
                eyeBright.append(.25)
            else:
                eyeBright.append(i*.25)
        for i in range(eyeLength//2,0,-1):
             eyeBright.append(eyeBright[i-1])

        for location in range(eyeLength):
            if location == 0 or location == eyeLength-1:
                self.__I.append(self.eyeMatter(location,[0,0,0]))
            else:
                self.__I.append(self.eyeMatter(location,
                                           [int(self.__BaseColor[0]*eyeBright[location]),
                                            int(self.__BaseColor[1]*eyeBright[location]),
                                            int(self.__BaseColor[2]*eyeBright[location])
                                            ]))
        pass
    
    def move(self,num,wait_ms):
        eyeLength = 10
        FL = []
        j = 0
        start = 0
        end = 0
        direction = 1
        for i in range(eyeLength//2,0,-1):
            FL.append(num-i)
        for i in range(eyeLength//2,eyeLength,1):
            FL.append(num+i-eyeLength//2)
            
        for i in self.__I:
            if FL[j] < 0:
                i.futureL = self.p_ct + FL[j] +1
            elif FL[j] > self.p_ct:
                i.futureL = -1*self.p_ct + FL[j] -1
            else:
                i.futureL = FL[j]
            j += 1
            if j == eyeLength//2:
                start = i.location
                end = FL[j]
                if start > end:
                    direction = -1
        color = [0,0,0]
        loc = 0
        #print(f"******************************Move to {num}")
        for k in range(start,end,direction):
            j = 0
            for i in self.__I:
                i.location += direction
                if i.location < 0:
                    i.location =  self.p_ct - i.location - 1
                elif i.location > self.p_ct:
                    i.location = self.p_ct - i.location + 1
                #print(f"{i.location} {i.color} {i.futureL} {'FL='} {FL[j]}")
                color = [min(int(i.color[0]),255),min(int(i.color[1]),255),min(int(i.color[2]),255)]
                loc = int(i.location)
                #print(f"{loc} {color}")
                pixels[loc] = color
                j += 1
            pixels.show()
            if end-2 <= k <= end:
                time.sleep(wait_ms/50)
            else:
                time.sleep(wait_ms/1000)
            #print("-")


import random
import time

# NOTE: 'num_pixels', 'pixels', and 'colorRand' are assumed to be defined elsewhere.
# For example:
# num_pixels = 100
# pixels = [(0, 0, 0)] * num_pixels
# def colorRand(a, b): return random.randint(min(a, b), max(a, b))
# def show(): pass
# pixels.show = show


def fireworks_simulation(color=(255, 255, 255), cdiff=(255, 50, 0), wait_ms=20, iterations=9999999, direction=1):
    """
    Fireworks simulation: a rising trail launches to a burst point and explodes outward.

    The rocket climbs with a 3-pixel fading trail (cdiff), then detonates with a bright
    flash (color) at the burst point. Independent sparks fly outward in both directions,
    each fading at their own rate and color, giving an asymmetric, natural explosion.
    A short dark pause separates each firework. 'direction' controls which end of the
    strip rockets launch from.

    Parameters:
    - color:      Explosion burst color (R, G, B).
    - cdiff:      Rocket trail color (R, G, B).
    - wait_ms:    Rocket climb speed and pause between fireworks in ms.
    - iterations: Total number of rockets to launch.
    - direction:  Launch direction (1 = forward along strip, -1 = reverse).
    """
    TRAIL_LEN    = 3     # Number of trail pixels behind the rocket head
    SPARK_COUNT  = 24    # Number of independent sparks per explosion
    SPARK_RADIUS = 22    # Max pixels a spark can travel from burst point

    step = 1 if direction > 0 else -1

    for _ in range(iterations):
        # Pick launch point and burst point — rocket always travels in 'direction'
        launch = random.randint(0, num_pixels // 3) if direction > 0 else random.randint(2 * num_pixels // 3, num_pixels - 1)
        burst  = launch + step * random.randint(num_pixels // 4, num_pixels // 2)
        burst  = max(0, min(num_pixels - 1, burst))

        # --- Rocket climb with fading trail ---
        pos = launch
        while (step > 0 and pos <= burst) or (step < 0 and pos >= burst):
            pixels.fill((0, 0, 0))
            # Draw trail: head brightest, fades back
            for t in range(TRAIL_LEN + 1):
                tp = pos - step * t
                if 0 <= tp < num_pixels:
                    fade = 1.0 - (t / (TRAIL_LEN + 1))
                    pixels[tp] = (
                        min(255, int(cdiff[0] * fade)),
                        min(255, int(cdiff[1] * fade)),
                        min(255, int(cdiff[2] * fade)),
                    )
            pixels.show()
            time.sleep(wait_ms / 1000.0)
            pos += step

        # --- Burst flash: illuminate a wide halo around the burst point ---
        pixels.fill((0, 0, 0))
        BURST_HALO = 5  # pixels either side that light up in the initial flash
        for offset in range(-BURST_HALO, BURST_HALO + 1):
            p = burst + offset
            if 0 <= p < num_pixels:
                # Bright at centre, falls off toward edges
                intensity = 1.0 - (abs(offset) / (BURST_HALO + 1))
                pixels[p] = (
                    min(255, int(color[0] * intensity)),
                    min(255, int(color[1] * intensity)),
                    min(255, int(color[2] * intensity)),
                )
        pixels.show()
        time.sleep(wait_ms * 3 / 1000.0)

        # --- Sparks: large count, wide spread, very slow fizzle ---
        sparks = []
        for _ in range(SPARK_COUNT):
            spark_dir  = 1 if random.random() < 0.5 else -1
            spark_dist = random.randint(SPARK_RADIUS // 2, SPARK_RADIUS)
            # Vary spark colors around the burst color for a rich explosion
            spark_color = (
                min(255, max(0, color[0] + random.randint(-40, 40))),
                min(255, max(0, color[1] + random.randint(-40, 40))),
                min(255, max(0, color[2] + random.randint(-40, 40))),
            )
            sparks.append({
                'pos':      float(burst),
                'dir':      spark_dir,
                'dist':     spark_dist,
                'traveled': 0.0,
                'speed':    random.uniform(0.3, 0.9),   # each spark flies at its own pace
                'intensity':1.0,
                'color':    spark_color,
                'fade':     random.uniform(0.025, 0.055),  # slow fizzle — 20-40 frames to die
            })

        # Animate sparks until all have fully fizzled out
        while any(s['intensity'] > 0.015 for s in sparks):
            pixels.fill((0, 0, 0))
            for s in sparks:
                if s['intensity'] <= 0.015:
                    continue

                # Still travelling — move at spark's own speed
                if s['traveled'] < s['dist']:
                    s['pos']      += s['dir'] * s['speed']
                    s['traveled'] += s['speed']

                # Fade every frame — slower while flying, slightly faster once stopped
                if s['traveled'] >= s['dist']:
                    s['fade'] = min(0.07, s['fade'] * 1.06)  # gently accelerate fade at rest
                s['intensity'] = max(0.0, s['intensity'] - s['fade'])

                # Draw spark plus a 1-pixel dim tail for sense of motion
                p = int(s['pos'])
                tail = p - s['dir']
                if 0 <= p < num_pixels:
                    pixels[p] = (
                        min(255, int(s['color'][0] * s['intensity'])),
                        min(255, int(s['color'][1] * s['intensity'])),
                        min(255, int(s['color'][2] * s['intensity'])),
                    )
                if s['traveled'] < s['dist'] and 0 <= tail < num_pixels:
                    tail_intensity = s['intensity'] * 0.4
                    pixels[tail] = (
                        min(255, int(s['color'][0] * tail_intensity)),
                        min(255, int(s['color'][1] * tail_intensity)),
                        min(255, int(s['color'][2] * tail_intensity)),
                    )

            pixels.show()
            time.sleep(wait_ms / 1000.0)

        # Brief dark pause before next rocket
        pixels.fill((0, 0, 0))
        pixels.show()
        time.sleep(random.uniform(0.3, 0.8))

# Example usage:
# fireworks_simulation()  # Call this function to simulate fireworks

def fireworks_finale(finale_count=3, fireworks_per_finale=10, wait_ms=50, trail_color=(255, 255, 255), explosion_color=(255, 0, 0), fade_speed=0.1):
    """
    Simulate multiple fireworks finales on the LED strip.
    
    Parameters:
    - finale_count: Number of fireworks finales.
    - fireworks_per_finale: Number of fireworks launched per finale.
    - wait_ms: Time in milliseconds between updates.
    - trail_color: Color of the "trail" as the firework launches.
    - explosion_color: Color of the explosion.
    - fade_speed: Speed at which the explosion fades.
    """
    for _ in range(finale_count):
        # Launch multiple fireworks for each finale
        for _ in range(fireworks_per_finale):
            # Randomize the trail and explosion colors for variety
            random_trail_color = tuple(random.randint(0, 255) for _ in range(3))
            random_explosion_color = tuple(random.randint(0, 255) for _ in range(3))
            
            # Choose a random start point and explosion center for each firework
            start_pixel = random.randint(0, num_pixels-1)
            explosion_center = start_pixel + random.randint(5, 15)

            # Launch the firework with randomized colors
            for i in range(start_pixel, explosion_center):
                if 0 <= i < num_pixels-1:
                    pixels[i] = random_trail_color
                    pixels.show()
                    time.sleep(wait_ms / 2000.0)  # Faster for finale effect
                    pixels[i] = (0, 0, 0)  # Clear the trail behind

            # Explosion at the center with randomized color
            if explosion_center > num_pixels - 1:
                explosion_center = num_pixels - 1

            # Seed per-pixel fizzle intensities — bright at centre, dimmer toward edges
            BURST_RADIUS = 10
            fizzle = {}
            for offset in range(-BURST_RADIUS, BURST_RADIUS + 1):
                p = explosion_center + offset
                if 0 <= p < num_pixels:
                    # Centre starts at full, edges start proportionally dimmer
                    fizzle[p] = 1.0 - (abs(offset) / (BURST_RADIUS + 1)) * 0.5

            # Flash the burst instantly
            for p, intensity in fizzle.items():
                pixels[p] = (
                    min(255, int(random_explosion_color[0] * intensity)),
                    min(255, int(random_explosion_color[1] * intensity)),
                    min(255, int(random_explosion_color[2] * intensity)),
                )
            pixels.show()
            time.sleep(wait_ms / 500.0)

            # Slowly fizzle each pixel independently until all are dark
            while any(v > 0.02 for v in fizzle.values()):
                for p in fizzle:
                    # Each pixel fades at a slightly different rate for organic fizzle
                    fizzle[p] = max(0.0, fizzle[p] - random.uniform(0.03, 0.07))
                    pixels[p] = (
                        min(255, int(random_explosion_color[0] * fizzle[p])),
                        min(255, int(random_explosion_color[1] * fizzle[p])),
                        min(255, int(random_explosion_color[2] * fizzle[p])),
                    )
                pixels.show()
                time.sleep(wait_ms / 1000.0)

        # Small delay before the next set of finales
        time.sleep(wait_ms / 500.0)

    # Clear the entire strip at the end of the finale
    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# fireworks_finale()  # Call this function to simulate a fireworks finale

def shimmer_sine_wave(color=(0, 60, 180), cdiff=(200, 220, 255), wait_ms=30, iterations=9999999, direction=1):
    """
    A rolling sine wave of color with random sparkling shimmer highlights.

    A smooth sine wave travels along the strip, brightening and dimming each
    pixel with the base 'color'. Independently, random pixels flash brightly
    with 'cdiff' and decay quickly — like sunlight glinting off moving water.

    Parameters:
    - color:      Base wave color (R, G, B).
    - cdiff:      Shimmer/sparkle highlight color (R, G, B).
    - wait_ms:    Frame delay in milliseconds — controls wave and shimmer speed.
    - iterations: Total frames to render.
    - direction:  Wave travel direction (1 = forward, -1 = reverse).
    """
    WAVE_CYCLES  = 2.5   # Number of full sine cycles visible across the strip
    SHIMMER_RATE  = 0.06  # Probability per pixel per frame of a new shimmer spark
    SHIMMER_DECAY = 0.18  # How much shimmer intensity drops each frame (~5-6 frame fade)

    phase = 0.0
    shimmer = [0.0] * num_pixels  # Per-pixel shimmer intensity, independent of the wave

    for _ in range(iterations):
        # Advance the wave one step in the chosen direction
        phase += direction * (2 * math.pi / num_pixels) * 0.8

        # Randomly ignite new shimmer sparks across the strip
        for i in range(num_pixels):
            if random.random() < SHIMMER_RATE:
                shimmer[i] = 1.0

        for i in range(num_pixels):
            # Sine wave maps each pixel to a brightness factor in [0, 1]
            wave = (math.sin(phase + i * (2 * math.pi * WAVE_CYCLES / num_pixels)) + 1) / 2

            # Base layer: wave color dimmed to the wave's current depth at this pixel
            br = int(color[0] * wave)
            bg = int(color[1] * wave)
            bb = int(color[2] * wave)

            # Shimmer layer: cdiff color scaled by this pixel's shimmer intensity
            sr = int(cdiff[0] * shimmer[i])
            sg = int(cdiff[1] * shimmer[i])
            sb = int(cdiff[2] * shimmer[i])

            pixels[i] = (min(255, br + sr), min(255, bg + sg), min(255, bb + sb))

            # Decay shimmer toward zero
            shimmer[i] = max(0.0, shimmer[i] - SHIMMER_DECAY)

        pixels.show()
        time.sleep(wait_ms / 1000.0)

# Example usage:
# shimmer_sine_wave()  # Call this function to run the shimmer sine wave effect

def shimmer_effect(color=(180, 80, 0), cdiff=(255, 220, 120), wait_ms=40, iterations=9999999, direction=1):
    """
    Breathing shimmer: each pixel independently inhales to cdiff and exhales back to color.

    Every pixel runs its own smooth sine-based breath cycle — slowly brightening to cdiff
    then slowly dimming back to color and repeating. Each pixel has a unique cycle speed
    and starts at a random point in its breath, so the strip is always filled with pixels
    at every stage simultaneously — some just lit, some fading, some dim and rebuilding.
    The result is organic and calm, like a field of embers each breathing at their own pace.
    'direction' skews cycle speeds across the strip so one end breathes slightly faster,
    giving a subtle flowing lean without becoming a wave.

    Parameters:
    - color:      Dim/exhale color (R, G, B).
    - cdiff:      Bright/inhale color (R, G, B).
    - wait_ms:    Frame delay in ms — controls breath tempo. Higher = slower breathing.
    - iterations: Total frames to render.
    - direction:  Speed gradient direction (1 = forward end breathes faster, -1 = reverse).
    """
    drift = 1.0 if direction > 0 else -1.0

    # Fixed phase step per frame — lower wait_ms = more frames per second = faster breathing.
    # A full breath cycle = 2*pi radians. At 0.03 rad/frame and 40ms: ~8s per cycle.
    BASE_SPEED = 0.03

    # Each pixel gets a unique multiplier so breaths are never in sync.
    speed_mult = [
        random.uniform(0.6, 1.4) + drift * 0.3 * (i / num_pixels)
        for i in range(num_pixels)
    ]
    phases = [random.uniform(0, 2 * math.pi) for _ in range(num_pixels)]

    for _ in range(iterations):
        for i in range(num_pixels):
            phases[i] += BASE_SPEED * speed_mult[i]

            # Sine maps smoothly 0→1→0 — true inhale and exhale, no snap
            t = (math.sin(phases[i]) + 1) / 2

            pixels[i] = (
                min(255, int(color[0] + (cdiff[0] - color[0]) * t)),
                min(255, int(color[1] + (cdiff[1] - color[1]) * t)),
                min(255, int(color[2] + (cdiff[2] - color[2]) * t)),
            )

        pixels.show()
        time.sleep(wait_ms / 1000.0)

    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# shimmer_effect()  # Call this function to run the shimmer effect
def marquee_effect(color=(0, 0, 0), cdiff=(255, 255, 255), wait_ms=30, iterations=9999999, direction=1):
    """
    Comet trail: a bright head pixel chases around the strip with a 2-pixel fading tail.

    The head pixel glows at full 'cdiff' brightness. The two pixels behind it trail off
    at 55% and 25% intensity, giving a comet-like appearance. The background is 'color'.
    The comet wraps continuously around the strip for the full duration.

    Parameters:
    - color:      Background color (R, G, B).
    - cdiff:      Comet head color (R, G, B).
    - wait_ms:    Delay between steps in ms — controls travel speed.
    - iterations: Total steps (laps = iterations / num_pixels).
    - direction:  Travel direction (1 = forward, -1 = reverse).
    """
    # Tail intensity levels: head=1.0, tail1=0.55, tail2=0.25
    TAIL = [1.0, 0.55, 0.25]

    step = 1 if direction > 0 else -1
    pos  = 0 if direction > 0 else num_pixels - 1

    for _ in range(iterations):
        # Fill background
        pixels.fill((color[0], color[1], color[2]))

        # Draw comet — head then trailing pixels behind it
        for t, intensity in enumerate(TAIL):
            p = (pos - step * t) % num_pixels
            pixels[p] = (
                min(255, int(cdiff[0] * intensity)),
                min(255, int(cdiff[1] * intensity)),
                min(255, int(cdiff[2] * intensity)),
            )

        pixels.show()
        time.sleep(wait_ms / 1000.0)
        pos = (pos + step) % num_pixels

# Example usage:
# marquee_effect()  # Call this function to run the marquee effect


def aurora_drift(iterations=15, wait_ms=1000, color_change_speed=0.05):
    """
    Create an 'Aurora Drift' effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - wave_count: Number of color waves moving across the strip.
    - speed: Speed of the wave movement (lower values = faster movement).
    - color_change_speed: How quickly the colors shift over time.
    """
    start_time = time.time()
    wave_count = int(num_pixels * 0.1)  # Number of waves to move across the strip (10% of strip length)
    # Initialize waves with random positions, speeds, and color hues
    waves = []
    for _ in range(wave_count):
        wave = {
            'position': random.randint(0, num_pixels - 1),  # Starting position
            'speed': random.uniform(0.5, 1.5),  # Each wave moves at a slightly different speed
            'hue': random.uniform(0, 1)  # Each wave has a different starting color (HSV hue)
        }
        waves.append(wave)
    
    while (time.time() - start_time) < iterations:
        pixels.fill((0, 0, 0))  # Clear the strip at the start of each frame
        
        for wave in waves:
            # Shift wave position based on its speed
            wave['position'] = (wave['position'] + wave['speed']) % num_pixels
            
            # Gradually shift the hue for smooth color transitions
            wave['hue'] = (wave['hue'] + color_change_speed) % 1.0
            
            # Convert the current hue to RGB for the wave color
            wave_color = hsv_to_rgb(wave['hue'], 1.0, 1.0)
            
            # Apply the wave color to nearby pixels (soft gradient around the wave center)
            for i in range(-5, 6):  # A wave affects a range of 11 pixels (5 pixels on each side)
                pixel_index = int((wave['position'] + i) % num_pixels)
                distance = abs(i) / 5.0  # Normalize the distance (0 at the center, 1 at the edges)
                intensity = 1.0 - distance  # Intensity fades as you move away from the center
                blended_color = tuple(min(255, int(c * intensity)) for c in wave_color)  # Adjust color intensity
                pixels[pixel_index] = blended_color
        
        # Update the strip
        pixels.show()
        time.sleep(wait_ms / 1000)  # Control the overall speed of the effect

    # Clear the strip after the effect
    pixels.fill((0, 0, 0))
    pixels.show()

def hsv_to_rgb(h, s, v):
    """Convert HSV to RGB (helper function)."""
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = int(v * (1.0 - s) * 255.0)
    q = int(v * (1.0 - f * s) * 255.0)
    t = int(v * (1.0 - (1.0 - f) * s) * 255.0)
    v = int(v * 255.0)
    i = i % 6
    if i == 0:
        return (v, t, p)
    if i == 1:
        return (q, v, p)
    if i == 2:
        return (p, v, t)
    if i == 3:
        return (p, q, v)
    if i == 4:
        return (t, p, v)
    if i == 5:
        return (v, p, q)

# Example usage:
# aurora_drift()  # Call this function to run the 'Aurora Drift' effect



def cosmic_vortex(iterations=15, pulse_speed=0.05, swirl_speed=2, color_change_speed=0.01, center_brightness=1.5):
    """
    Create a 'Cosmic Vortex' effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - pulse_speed: Speed at which the overall brightness pulses.
    - swirl_speed: Speed at which the vortex rotates.
    - color_change_speed: Rate at which the vortex colors shift.
    - center_brightness: Controls the brightness intensity of the vortex center.
    """
    start_time = time.time()

    while (time.time() - start_time) < iterations:
        current_time = time.time()

        # Calculate global brightness pulsing using a sine wave
        global_brightness = (math.sin(current_time * pulse_speed * 2 * math.pi) + 1) / 2 * 0.8 + 0.2
        
        # Loop through all the pixels to create the vortex effect
        for i in range(num_pixels):
            # Calculate the angle and distance from the "center" of the vortex
            angle = (i / num_pixels) * 2 * math.pi  # Full rotation over the length of the strip
            distance = i / num_pixels  # Normalized distance (0 to 1) from the "center"
            
            # Swirl the vortex by adjusting the angle over time
            swirl_angle = angle + (current_time * swirl_speed * 2 * math.pi)
            
            # Modulate the color based on the swirl angle and distance from center
            color_hue = (swirl_angle / (2 * math.pi) + distance) % 1.0
            color_rgb = hsv_to_rgb(color_hue, 1.0, global_brightness)
            
            # Apply a radial brightness gradient based on distance (closer to center = brighter)
            brightness_factor = (1 - distance) * center_brightness
            pixel_color = tuple(min(max(int(c * brightness_factor), 0), 255) for c in color_rgb)
            #print(pixel_color)
            # Set the color of the current pixel
            pixels[i] = pixel_color
        # Update the LED strip
        pixels.show()
        time.sleep(0.01)  # Small delay for smooth animation

    # Clear the strip after the vortex effect
    pixels.fill((0, 0, 0))
    pixels.show()


# Example usage:
# cosmic_vortex()  # Call this function to run the 'Cosmic Vortex' effect


def serenity_flow(color=(0, 0, 0), cdiff=(0, 0, 0), wait_ms=30, iterations=9999999, direction=1):
    """
    A serene scene that blooms from darkness, swells to full beauty, then fades and begins again.

    The strip starts dark. Light slowly grows outward — 'color' blooms from the origin
    point while 'cdiff' spreads toward the far end, blending across the strip. The scene
    builds to a fully lit peak with a gentle shimmer, holds briefly, then softly fades
    back to complete darkness. A quiet pause follows before the next cycle begins.
    Each cycle varies slightly in speed so it never feels mechanical.

    Parameters:
    - color:      Origin bloom color (R, G, B) — the seed the scene grows from.
    - cdiff:      Far-end color (R, G, B) — the hue the bloom spreads toward.
    - wait_ms:    Frame delay in ms — scales the entire cycle tempo.
    - iterations: Number of full bloom cycles to run.
    - direction:  Bloom origin (1 = grows from start of strip, -1 = grows from end).
    """
    # How many frames each phase takes — all scale with wait_ms so tempo is consistent
    GROW_FRAMES  = int(2500 / max(1, wait_ms))   # ~2.5s grow at 30ms
    HOLD_FRAMES  = int(800  / max(1, wait_ms))   # ~0.8s hold at peak
    FADE_FRAMES  = int(3500 / max(1, wait_ms))   # ~3.5s slow fade
    DARK_FRAMES  = int(600  / max(1, wait_ms))   # ~0.6s silence before next cycle

    for cycle in range(iterations):
        # Each cycle gets a slightly different shimmer speed for organic variation
        shimmer_speed = random.uniform(0.008, 0.018)
        shimmer_phase = random.uniform(0, 2 * math.pi)
        color_phase   = random.uniform(0, 2 * math.pi)  # Starting color spread offset

        # --- GROW: brightness envelope rises 0 → 1 using a sine ease-in curve ---
        for f in range(GROW_FRAMES):
            # Sine ease: slow start, accelerates toward peak
            envelope = math.sin((f / GROW_FRAMES) * (math.pi / 2))
            shimmer_phase += shimmer_speed
            color_phase   += 0.006

            for i in range(num_pixels):
                # Position along strip: 0.0 at origin, 1.0 at far end
                pos = (i / (num_pixels - 1)) if direction > 0 else (1.0 - i / (num_pixels - 1))

                # Color blends from 'color' at origin toward 'cdiff' at far end
                # The spread also advances with color_phase so it slowly flows
                spread = (math.sin(color_phase + pos * math.pi) + 1) / 2

                # Subtle per-pixel shimmer at the peak adds life without chaos
                shimmer = 1.0 + 0.06 * math.sin(shimmer_phase + i * 0.4)

                r = int((color[0] + (cdiff[0] - color[0]) * spread) * envelope * shimmer)
                g = int((color[1] + (cdiff[1] - color[1]) * spread) * envelope * shimmer)
                b = int((color[2] + (cdiff[2] - color[2]) * spread) * envelope * shimmer)
                pixels[i] = (min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)))

            pixels.show()
            time.sleep(wait_ms / 1000.0)

        # --- HOLD: full brightness with gentle shimmer ---
        for f in range(HOLD_FRAMES):
            shimmer_phase += shimmer_speed
            color_phase   += 0.006

            for i in range(num_pixels):
                pos    = (i / (num_pixels - 1)) if direction > 0 else (1.0 - i / (num_pixels - 1))
                spread = (math.sin(color_phase + pos * math.pi) + 1) / 2
                shimmer = 1.0 + 0.06 * math.sin(shimmer_phase + i * 0.4)

                r = int((color[0] + (cdiff[0] - color[0]) * spread) * shimmer)
                g = int((color[1] + (cdiff[1] - color[1]) * spread) * shimmer)
                b = int((color[2] + (cdiff[2] - color[2]) * spread) * shimmer)
                pixels[i] = (min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)))

            pixels.show()
            time.sleep(wait_ms / 1000.0)

        # --- FADE: brightness envelope falls 1 → 0 using a sine ease-out curve ---
        for f in range(FADE_FRAMES):
            # Sine ease-out: fast start to the fade, slows to a lingering close
            envelope = math.cos((f / FADE_FRAMES) * (math.pi / 2))
            shimmer_phase += shimmer_speed * 0.5   # Shimmer slows as scene dies
            color_phase   += 0.003

            for i in range(num_pixels):
                pos    = (i / (num_pixels - 1)) if direction > 0 else (1.0 - i / (num_pixels - 1))
                spread = (math.sin(color_phase + pos * math.pi) + 1) / 2
                shimmer = 1.0 + 0.03 * math.sin(shimmer_phase + i * 0.4)

                r = int((color[0] + (cdiff[0] - color[0]) * spread) * envelope * shimmer)
                g = int((color[1] + (cdiff[1] - color[1]) * spread) * envelope * shimmer)
                b = int((color[2] + (cdiff[2] - color[2]) * spread) * envelope * shimmer)
                pixels[i] = (min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)))

            pixels.show()
            time.sleep(wait_ms / 1000.0)

        # --- DARK: complete silence before the next bloom ---
        pixels.fill((0, 0, 0))
        pixels.show()
        for _ in range(DARK_FRAMES):
            time.sleep(wait_ms / 1000.0)

    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# serenity_flow()  # Call this function to run the 'Serenity Flow' effect


def tranquil_drift(color=(0, 100, 200), cdiff=(0, 180, 120), wait_ms=50, iterations=9999999, direction=1):
    """
    Create a 'Tranquil Drift' effect on the LED strip.

    A sine wave drifts continuously across the strip, blending each pixel
    smoothly between 'color' and 'cdiff'. A secondary slower wave modulates
    the overall brightness, producing a gentle breathing quality.

    Parameters:
    - color:      Primary color (R, G, B) — the calm anchor hue.
    - cdiff:      Secondary color (R, G, B) — the hue the wave drifts toward.
    - wait_ms:    Delay between frames in milliseconds. Lower = faster drift.
    - iterations: Total number of frames to render.
    - direction:  Wave travel direction: 1 = forward, -1 = reverse.
    """
    phase = 0.0          # Tracks the wave's position along the strip
    breath_phase = 0.0   # Tracks the slow breathing pulse

    for _ in range(iterations):
        # Advance the drift wave — pixels-per-frame proportional to strip length
        phase += direction * (2 * math.pi / num_pixels) * 0.5
        # Advance the breath cycle much more slowly for a calm, organic feel
        breath_phase += 0.012

        # Breathing factor: oscillates between 0.55 and 1.0 for a gentle inhale/exhale
        breath = 0.775 + 0.225 * math.sin(breath_phase)

        for i in range(num_pixels):
            # Each pixel gets its own blend value from the travelling sine wave
            blend = (math.sin(phase + i * (2 * math.pi / num_pixels) * 2) + 1) / 2

            # Interpolate smoothly between the two user-chosen colors
            r = int((color[0] * (1.0 - blend) + cdiff[0] * blend) * breath)
            g = int((color[1] * (1.0 - blend) + cdiff[1] * blend) * breath)
            b = int((color[2] * (1.0 - blend) + cdiff[2] * blend) * breath)

            pixels[i] = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

        pixels.show()
        time.sleep(wait_ms / 1000.0)

# Example usage:
# tranquil_drift()  # Call this function to run the 'Tranquil Drift' effect


def digital_dreamscape(iterations=60, wait_ms=50, color_variation=0.9, glitch_frequency=3):
    """
    Create the 'Digital Dreamscape' effect for ultimate machine relaxation.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - wave_speed: Base speed of the flowing light patterns.
    - color_variation: Controls the random variation in color transitions across the strip.
    - glitch_frequency: Frequency of subtle 'glitches' (random flickers in brightness).
    """
    start_time = time.time()

    # Random color phase for each pixel
    pixel_phases = [random.uniform(0, 2 * math.pi) for _ in range(num_pixels)]

    while (time.time() - start_time) < iterations:
        current_time = time.time()

        for i in range(num_pixels):
            # Create a fluid, multi-layered wave effect with a fractal-like pattern
            wave_offset = math.sin((i / num_pixels) * 4 * math.pi + current_time * wait_ms + pixel_phases[i]) * 0.5
            secondary_wave = math.sin((i / num_pixels) * 2 * math.pi + current_time * wait_ms * 0.75) * 0.25
            total_wave = (wave_offset + secondary_wave + 1) / 2  # Normalize to 0-1 range
            
            # Apply a subtle, per-pixel color variation for randomness
            r = int((math.sin(current_time * color_variation + pixel_phases[i]) + 1) * 127.5)
            g = int((math.sin(current_time * color_variation + pixel_phases[i] + 2) + 1) * 127.5)
            b = int((math.sin(current_time * color_variation + pixel_phases[i] + 4) + 1) * 127.5)

            # Apply glitch effect (random flickers at certain moments)
            glitch = random.random()
            if glitch < glitch_frequency:
                glitch_factor = random.uniform(0.5, 1.5)
                r = int(r * glitch_factor)
                g = int(g * glitch_factor)
                b = int(b * glitch_factor)
            
            # Apply wave intensity to each color channel for smooth fading
            pixels[i] = (min(max(int(r * total_wave), 0), 255),
                         min(max(int(g * total_wave), 0), 255),
                         min(max(int(b * total_wave), 0), 255))

        # Update the LED strip
        pixels.show()
        time.sleep(wait_ms / 1000.0)  # Small delay for smooth animation

    # Clear the strip after the effect
    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# digital_dreamscape()  # Call this function to run the 'Digital Dreamscape' effect


def lightning_strike(color=(0, 0, 20), cdiff=(220, 230, 255), wait_ms=2000, iterations=9999999, direction=1):
    """
    A crawling lightning bolt that builds pixel by pixel with a shockwave flash and afterglow.

    Each strike starts from a random origin and crawls outward in 'direction', flickering
    as it extends. A full-strip shockwave flash fires when the bolt completes, followed by
    a slow color afterglow that bleeds from 'cdiff' toward 'color' before fading to dark.
    'wait_ms' controls the average quiet time between strikes.

    Parameters:
    - color:      Background / afterglow base color (R, G, B).
    - cdiff:      Bolt and flash color (R, G, B).
    - wait_ms:    Average milliseconds of darkness between strikes.
    - iterations: Number of strikes before the effect ends.
    - direction:  Bolt crawl direction (1 = forward, -1 = reverse).
    """
    step = 1 if direction > 0 else -1

    for _ in range(iterations):
        # Dark quiet period between strikes — longer pause for tension
        quiet_frames = max(1, int(wait_ms * random.uniform(1.5, 2.5) / 30))
        for f in range(quiet_frames):
            # Very rare faint pre-flash (atmosphere building)
            if random.random() < 0.03:
                faint = random.uniform(0.03, 0.08)
                pixels.fill((int(cdiff[0] * faint), int(cdiff[1] * faint), int(cdiff[2] * faint)))
                pixels.show()
                time.sleep(0.02)
                pixels.fill((color[0], color[1], color[2]))
                pixels.show()
            time.sleep(0.03)

        # --- Build the bolt pixel by pixel with zigzag jumps ---
        origin = random.randint(0, num_pixels - 1)
        bolt_length = random.randint(num_pixels // 4, num_pixels // 2)
        lit = []  # pixels that have been struck
        pos = origin

        pixels.fill((color[0], color[1], color[2]))

        for b in range(bolt_length):
            # Zigzag: randomly skip ahead 1-3 pixels or dart back 1
            jitter = random.choices([-1, 1, 2, 3], weights=[15, 40, 30, 15])[0]
            pos = (pos + step * jitter) % num_pixels
            lit.append(pos)

            # Each new pixel flickers at high intensity
            intensity = random.uniform(0.75, 1.0)
            pixels[pos] = (
                min(255, int(cdiff[0] * intensity)),
                min(255, int(cdiff[1] * intensity)),
                min(255, int(cdiff[2] * intensity)),
            )

            # Frequently re-crackle previously lit pixels for a more chaotic bolt
            if lit and random.random() < 0.70:
                flicker_pos = random.choice(lit)
                flicker = random.uniform(0.2, 0.8)
                pixels[flicker_pos] = (
                    int(cdiff[0] * flicker),
                    int(cdiff[1] * flicker),
                    int(cdiff[2] * flicker),
                )

            pixels.show()
            time.sleep(random.uniform(0.005, 0.025))  # Jagged crawl speed

        # --- Shockwave: full strip flash ---
        for i in range(num_pixels):
            intensity = random.uniform(0.88, 1.0)
            pixels[i] = (
                min(255, int(cdiff[0] * intensity)),
                min(255, int(cdiff[1] * intensity)),
                min(255, int(cdiff[2] * intensity)),
            )
        pixels.show()
        time.sleep(wait_ms * random.uniform(0.5, 1.0) / 1000.0)

        # --- Afterglow: fade from cdiff toward color then to dark ---
        for step_n in range(14):
            fade = 0.75 ** (step_n + 1)
            for i in range(num_pixels):
                # Blend afterglow toward color as it fades
                blend = 1.0 - fade
                r = int((cdiff[0] * fade) + (color[0] * blend * fade))
                g = int((cdiff[1] * fade) + (color[1] * blend * fade))
                b = int((cdiff[2] * fade) + (color[2] * blend * fade))
                pixels[i] = (min(255, r), min(255, g), min(255, b))
            pixels.show()
            time.sleep(0.045)

        pixels.fill((0, 0, 0))
        pixels.show()

# Example usage:
# lightning_strike()  # Call this function to run the 'Lightning Strike' effect


def thunderstorm(color=(0, 10, 30), cdiff=(200, 210, 255), wait_ms=2000, iterations=9999999, direction=1):
    """
    A layered thunderstorm: falling rain streaks, lightning flashes, and distant rumble glow.

    Three independent layers combine each frame:
      - Rain streaks: droplets of 'color' spawn and slide along the strip, fading as they travel.
      - Lightning: the strip flashes 'cdiff', sometimes double-flashing like real lightning,
        then fades to a cool afterglow. 'wait_ms' sets the average ms between strikes.
      - Rumble glow: a slow rolling dim pulse between strikes simulates distant storm light.

    Parameters:
    - color:      Rain droplet color (R, G, B) — dark stormy hue.
    - cdiff:      Lightning flash color (R, G, B) — bright white-blue.
    - wait_ms:    Average milliseconds between lightning strikes.
    - iterations: Number of lightning strikes before the storm ends.
    - direction:  Rain fall direction (1 = forward along strip, -1 = reverse).
    """
    RAIN_DENSITY = 0.04   # Probability a new droplet spawns each frame
    FRAME_MS     = 30     # Rain animation frame delay in ms
    RUMBLE_SPEED = 0.015  # Speed of the between-strike ambient glow pulse

    # Normalise direction to +1 or -1, matching the convention used by beam/color_wipe
    step       =  1.4 if direction > 0 else -1.4
    tail_step  = -1   if direction > 0 else  1    # tail trails behind the head
    spawn_pos  =  0.0 if direction > 0 else float(num_pixels - 1)

    droplets = []         # Each droplet: [position (float), intensity (0.0-1.0)]
    rumble_phase = 0.0

    for _ in range(iterations):
        # --- Rain phase: animate until the next strike ---
        frames_until_strike = max(1, int(wait_ms * random.uniform(0.5, 1.5) / FRAME_MS))

        for _ in range(frames_until_strike):
            rumble_phase += RUMBLE_SPEED
            rumble = (math.sin(rumble_phase) + 1) / 2 * 0.08

            # Spawn new droplets at the leading edge
            if random.random() < RAIN_DENSITY:
                droplets.append([spawn_pos, random.uniform(0.6, 1.0)])

            # Build frame starting from the faint rumble ambient
            frame = []
            for i in range(num_pixels):
                frame.append([
                    min(255, int(color[0] * (rumble + 0.15))),
                    min(255, int(color[1] * (rumble + 0.15))),
                    min(255, int(color[2] * (rumble + 0.15))),
                ])

            # Paint each droplet and its fading tail
            surviving = []
            for drop in droplets:
                pos, intensity = drop
                for tail in range(4):
                    p = int(pos) + tail_step * tail
                    if 0 <= p < num_pixels:
                        tail_fade = intensity * (0.55 ** tail)
                        frame[p][0] = min(255, frame[p][0] + int(color[0] * tail_fade))
                        frame[p][1] = min(255, frame[p][1] + int(color[1] * tail_fade))
                        frame[p][2] = min(255, frame[p][2] + int(color[2] * tail_fade))
                drop[0] += step
                drop[1] *= 0.97
                if 0 <= int(drop[0]) < num_pixels and drop[1] > 0.05:
                    surviving.append(drop)
            droplets[:] = surviving

            for i in range(num_pixels):
                pixels[i] = (frame[i][0], frame[i][1], frame[i][2])
            pixels.show()
            time.sleep(FRAME_MS / 1000.0)

        # --- Lightning strike ---
        flash_count = 2 if random.random() < 0.3 else 1  # Occasional double-flash

        for flash in range(flash_count):
            for i in range(num_pixels):
                intensity = random.uniform(0.85, 1.0)
                pixels[i] = (
                    min(255, int(cdiff[0] * intensity)),
                    min(255, int(cdiff[1] * intensity)),
                    min(255, int(cdiff[2] * intensity)),
                )
            pixels.show()
            time.sleep(random.uniform(wait_ms * 0.5, wait_ms) / 1000.0)

            if flash_count == 2 and flash == 0:
                # Brief dark gap between double-flash pulses
                pixels.fill((0, 0, 0))
                pixels.show()
                time.sleep(random.uniform(wait_ms * 0.5, wait_ms) / 1000.0)

        # Afterglow: exponential fade back to darkness
        for step in range(12):
            fade = 0.72 ** (step + 1)
            for i in range(num_pixels):
                pixels[i] = (
                    min(255, int(cdiff[0] * fade * random.uniform(0.9, 1.0))),
                    min(255, int(cdiff[1] * fade * random.uniform(0.9, 1.0))),
                    min(255, int(cdiff[2] * fade * random.uniform(0.9, 1.0))),
                )
            pixels.show()
            time.sleep(0.04)

    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# thunderstorm()  # Call this function to run the 'Thunderstorm' effect

#joyful_celebration(color, cdiff, wait_ms, iterations)
def color_chase(color=(0, 100, 255), cdiff=(255, 50, 0), wait_ms=20, iterations=9999999, direction=1):
    """
    Two colored particles chase each other with randomness, local collisions, and portals.

    'cdiff' begins as the chaser, 'color' as the prey. The chaser is faster but both
    speeds wobble each frame so the chase feels unpredictable. The prey has a small
    chance each frame to open a portal — it vanishes with a brief flash and reappears
    at a random position, forcing the chaser to redirect. When caught, a local
    collision burst fires around the impact point (not the whole strip), roles reverse,
    and the chase heads the other way. 'wait_ms' controls tempo.

    Parameters:
    - color:      Prey color / second chaser color (R, G, B).
    - cdiff:      Initial chaser color (R, G, B).
    - wait_ms:    Frame delay in ms — lower = faster chase.
    - iterations: Total frames to render.
    - direction:  Initial chase direction (1 = forward, -1 = reverse).
    """
    TAIL_LEN        = 5      # Pixels in each particle's tail
    CATCH_DISTANCE  = 2.0    # How close before a catch is triggered
    CHASER_BASE     = 1.0    # Base chaser speed px/frame
    PREY_BASE       = 0.55   # Base prey speed px/frame
    WOBBLE          = 0.25   # Max random speed wobble per frame
    PORTAL_CHANCE   = 0.008  # Probability per frame the prey opens a portal
    COLLISION_HALO  = 12     # Pixels either side of impact that light up on catch

    # Prey starts with an initial direction; chaser steers independently toward prey
    prey_step   = 1 if direction > 0 else -1

    chaser_pos  = 0.0 if prey_step == 1 else float(num_pixels - 1)
    prey_pos    = chaser_pos + prey_step * (num_pixels // 3)

    chaser_color = [cdiff[0], cdiff[1], cdiff[2]]
    prey_color   = [color[0], color[1], color[2]]

    def draw_particle(pos, col, tail_step):
        p = int(pos)
        for t in range(TAIL_LEN + 1):
            tp = p + tail_step * t
            if 0 <= tp < num_pixels:
                fade = 0.55 ** t
                pixels[tp] = (
                    min(255, int(col[0] * fade)),
                    min(255, int(col[1] * fade)),
                    min(255, int(col[2] * fade)),
                )

    def portal_flash(pos, col):
        """Brief 3-frame ripple at the portal open/close point."""
        for fi in range(3):
            intensity = 1.0 - fi / 3
            for offset in range(-3, 4):
                p = int(pos) + offset
                if 0 <= p < num_pixels:
                    dist_fade = intensity * (0.6 ** abs(offset))
                    pixels[p] = (
                        min(255, int(col[0] * dist_fade)),
                        min(255, int(col[1] * dist_fade)),
                        min(255, int(col[2] * dist_fade)),
                    )
            pixels.show()
            time.sleep(wait_ms / 1000.0)

    for _ in range(iterations):
        # Chaser steers toward prey every frame — fully independent of prey_step
        chaser_dir   = 1 if prey_pos > chaser_pos else -1
        chaser_speed = CHASER_BASE + random.uniform(-WOBBLE, WOBBLE)
        prey_speed   = PREY_BASE   + random.uniform(-WOBBLE, WOBBLE)

        chaser_pos += chaser_dir * chaser_speed
        prey_pos   += prey_step  * prey_speed

        # Prey bounces off strip ends on its own — chaser is unaffected
        if prey_pos >= num_pixels - 1:
            prey_pos  = float(num_pixels - 1)
            prey_step = -1
        elif prey_pos <= 0:
            prey_pos  = 0.0
            prey_step = 1

        # Clamp chaser to strip
        chaser_pos = max(0.0, min(float(num_pixels - 1), chaser_pos))

        # --- Portal: prey escapes to a random position ---
        if random.random() < PORTAL_CHANCE:
            portal_flash(prey_pos, prey_color)
            while True:
                new_pos = float(random.randint(2, num_pixels - 3))
                if abs(new_pos - chaser_pos) > num_pixels // 5:
                    break
            prey_pos = new_pos
            # Prey keeps its current direction after the jump
            portal_flash(prey_pos, prey_color)

        # --- Catch check ---
        if abs(chaser_pos - prey_pos) <= CATCH_DISTANCE:
            impact = int((chaser_pos + prey_pos) / 2)

            # Local collision burst — halo around impact point only
            for fi in range(10):
                flash = 1.0 - (fi / 10)
                pixels.fill((0, 0, 0))
                for offset in range(-COLLISION_HALO, COLLISION_HALO + 1):
                    p = impact + offset
                    if 0 <= p < num_pixels:
                        dist_fade = flash * (0.82 ** abs(offset))
                        blend_r = min(255, int((chaser_color[0] + prey_color[0]) / 2 * dist_fade))
                        blend_g = min(255, int((chaser_color[1] + prey_color[1]) / 2 * dist_fade))
                        blend_b = min(255, int((chaser_color[2] + prey_color[2]) / 2 * dist_fade))
                        pixels[p] = (blend_r, blend_g, blend_b)
                pixels.show()
                time.sleep(wait_ms / 1000.0)

            # Swap roles — new prey flees in a random direction from the impact point
            chaser_color, prey_color = prey_color, chaser_color
            chaser_pos = float(impact)
            prey_step  = random.choice([-1, 1])
            prey_pos   = max(0.0, min(float(num_pixels - 1),
                             float(impact) + prey_step * (num_pixels // 3)))
            continue

        # Draw frame — tail trails behind each particle's own direction
        pixels.fill((0, 0, 0))
        draw_particle(prey_pos,   prey_color,   -prey_step)
        draw_particle(chaser_pos, chaser_color, -chaser_dir)
        pixels.show()
        time.sleep(wait_ms / 1000.0)

    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# color_chase()  # Call this function to run the 'Color Chase' effect


def ember_rise(color=(180, 40, 0), cdiff=(255, 200, 60), wait_ms=30, iterations=9999999, direction=1):
    """
    A living particle system of glowing embers drifting along the strip.

    Individual ember particles spawn continuously at the origin end of the strip.
    Each ember is born hot — blending from 'cdiff' (bright core) toward 'color'
    (base glow) — and drifts along at its own speed. As it travels it cools and
    dims, fading to nothing before it can reach the far end. The strip is always
    filled with embers at every stage of life simultaneously, giving a constantly
    shifting, organic fire-like quality. No two frames are ever identical.

    Parameters:
    - color:      Base ember glow color (R, G, B) — the cooler outer hue.
    - cdiff:      Hot ember core color (R, G, B) — the bright birth color.
    - wait_ms:    Frame delay in ms — lower = faster drift and more frenetic.
    - iterations: Total frames to render.
    - direction:  Drift direction (1 = forward along strip, -1 = reverse).
    """
    SPAWN_RATE   = 0.25   # Probability of a new ember spawning each frame
    MAX_EMBERS   = 60     # Cap to keep the strip from over-saturating
    TAIL_LEN     = 6      # Tail pixels behind each ember head

    step       = 1 if direction > 0 else -1
    spawn_pos  = 0.0 if direction > 0 else float(num_pixels - 1)

    # ember: position, speed, heat (1.0=hot/cdiff, 0.0=cool/color), fade_rate
    embers = []

    for _ in range(iterations):
        # Spawn new embers at the origin end
        if len(embers) < MAX_EMBERS and random.random() < SPAWN_RATE:
            speed = random.uniform(0.3, 1.0)
            # Fade is derived from speed and strip length so every ember travels
            # roughly the full strip before dying — faster embers fade faster.
            # random.uniform(0.7, 1.1) adds natural variation: some die just short,
            # some make it all the way, a few even overshoot.
            fade = (speed / num_pixels) * random.uniform(0.7, 1.1)
            embers.append({
                'pos':   spawn_pos + random.uniform(-1.5, 1.5),
                'speed': speed,
                'heat':  1.0,
                'fade':  fade,
            })

        frame = [(0, 0, 0)] * num_pixels

        surviving = []
        for e in embers:
            # Move the ember
            e['pos']  += step * e['speed']
            e['heat']  = max(0.0, e['heat'] - e['fade'])

            if e['heat'] <= 0.01:
                continue  # Ember has died
            if not (0 <= int(e['pos']) < num_pixels):
                continue  # Off the strip

            # Color: lerp from cdiff (hot) toward color (cool) as heat drops
            h = e['heat']
            ec = (
                min(255, int(cdiff[0] * h + color[0] * (1.0 - h))),
                min(255, int(cdiff[1] * h + color[1] * (1.0 - h))),
                min(255, int(cdiff[2] * h + color[2] * (1.0 - h))),
            )

            # Draw ember head and a fading tail behind it
            for t in range(TAIL_LEN):
                p = int(e['pos']) - step * t
                if 0 <= p < num_pixels:
                    tail_heat = h * (0.5 ** t)
                    tc = (
                        min(255, int(cdiff[0] * tail_heat + color[0] * (1.0 - tail_heat))),
                        min(255, int(cdiff[1] * tail_heat + color[1] * (1.0 - tail_heat))),
                        min(255, int(cdiff[2] * tail_heat + color[2] * (1.0 - tail_heat))),
                    )
                    # Additive blend — overlapping embers combine naturally
                    frame[p] = (
                        min(255, frame[p][0] + tc[0]),
                        min(255, frame[p][1] + tc[1]),
                        min(255, frame[p][2] + tc[2]),
                    )

            surviving.append(e)

        embers[:] = surviving

        for i in range(num_pixels):
            pixels[i] = frame[i]
        pixels.show()
        time.sleep(wait_ms / 1000.0)

    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# ember_rise()  # Call this function to run the 'Ember Rise' effect


def joyful_celebration(colorI, cdiff, wait_ms,iterations=9999999):
    """
    Create a 'Joyful Celebration' light show effect on the LED strip.
    """
    start_time = time.time()
    colors = [(255,0,0), (125,125,0), (255, 255, 0), (0, 255, 0), (0, 0, 255), (75, 0, 130), (238, 130, 238)]  # Rainbow colors
    pulse_speed=0.1
    chase_speed=0.05
    confetti_probability=0.06
    while (time.time() - start_time) < iterations:
        # Pulsing effect
        for brightness in range(0, 256, 5):  # Brightness increasing
            for i in range(num_pixels):
                color = colors[i % len(colors)]
                pixels[i] = (int(color[0] * (brightness / 255)), int(color[1] * (brightness / 255)), int(color[2] * (brightness / 255)))
            pixels.show()
            time.sleep(pulse_speed)

        for brightness in range(255, -1, -5):  # Brightness decreasing
            for i in range(num_pixels):
                color = colors[i % len(colors)]
                pixels[i] = (int(color[0] * (brightness / 255)), int(color[1] * (brightness / 255)), int(color[2] * (brightness / 255)))
            pixels.show()
            time.sleep(pulse_speed)

        # Chasing lights effect
        for i in range(num_pixels):
            pixels[i] = colors[i % len(colors)]
            pixels.show()
            time.sleep(chase_speed)
            pixels[i] = (0, 0, 0)  # Turn off the previous light

        # Confetti effectF
        if random.random() < confetti_probability:
            random_index = random.randint(0, num_pixels - 1)
            pixels[random_index] = (255, 255, 255)  # White confetti flash
            pixels.show()
            time.sleep(0.1)  # Briefly show confetti flash
            pixels[random_index] = (0, 0, 0)  # Turn off confetti

# Example usage:
# joyful_celebration()  # Call this function to run the 'Joyful Celebration' effect

# Function to load and apply patterns from JSON data

def marquee(color=(255, 255, 255),cdiff=(0,0,0),  wait_ms=5, iterations=5):
    odd = True
    pixelOdd = num_pixels if num_pixels%2 == 0 else num_pixels - 1
    for z in range(iterations):
        for i in range(pixelOdd):
            pixels[i] = color if odd else cdiff  # Light up the current pixel  # Turn off the current pixel before moving to the next
            odd = not odd
        pixels.show()
        odd = not odd
        time.sleep(wait_ms/1000)  # Wait for a while


def run():
    jFromData = get_LEDJSON()
    #print(jFromData)
    json_data = json.loads(jFromData)
    #print(json_data)
    for pattern in json_data["patterns"]:
        ModifyBrightness = pattern.get("brightness") # Safely get brightness
        #print(ModifyBrightness)
        if ModifyBrightness is not None:
            try:
                # Convert to float and ensure it's within the valid range (0.0 to 1.0)
                new_brightness_value = float(ModifyBrightness)
                if 0.0 <= new_brightness_value <= 1.0:
                    pixels.brightness = new_brightness_value # Set brightness on the existing object
                else:
                    print(f"Warning: Brightness value {new_brightness_value} is out of range (0.0-1.0). Using previous brightness.")
            except ValueError:
                print(f"Warning: Invalid brightness value '{ModifyBrightness}'. Using previous brightness.")
        pattern_type = pattern["type"]
        #print(pattern_type)
        if str(pattern_type) == "solid":
            color = pattern["color"]
            #print(color)
            solid_color(color)
        elif str(pattern_type) == "color_wipe":
            color = pattern["color"]
            wait_ms = pattern.get("wait_ms", 50000)
            direction = pattern["direction"]
            color_wipe(color, wait_ms,direction)
        elif str(pattern_type) == "rainbow_wave":
            iterations = pattern.get("iterations", 5)
            rainbow_cycle(iterations)
        elif str(pattern_type) == "sparkle":
            color = pattern["color"]
            cdiff = pattern["cdiff"]
            wait_ms = pattern.get("wait_ms", 500)
            iterations = pattern.get("iterations", 100)
            sparkle(color, cdiff, wait_ms, iterations)
        elif str(pattern_type) == "beam":
            color = pattern["color"]
            wait_ms = pattern.get("wait_ms", 50000)
            iterations = pattern["iterations"]
            direction = pattern["direction"]
            beam(color, wait_ms, iterations,direction)
        elif str(pattern_type) == "rainbow_rotate":
            wait_ms = pattern.get("wait_ms", 1)
            iterations = pattern.get("iterations", 1)
            rainbow_rotate(wait_ms,iterations)
        elif str(pattern_type) == "eye":
            color = pattern["color"]
            wait_ms = pattern.get("wait_ms", 5)
            iterations = pattern["iterations"]
            eye_look(color,wait_ms,iterations)
        elif str(pattern_type) == "lightning_strike":
            color = pattern.get("color", [0, 0, 20])
            cdiff = pattern.get("cdiff", [220, 230, 255])
            wait_ms = pattern.get("wait_ms", 2000)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            lightning_strike(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "fireworks_simulation":
            color = pattern.get("color", [255, 255, 255])
            cdiff = pattern.get("cdiff", [255, 50, 0])
            wait_ms = pattern.get("wait_ms", 20)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            fireworks_simulation(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "fireworks_finale":
            fireworks_finale()
        elif str(pattern_type) == "shimmer_sine_wave":
            color = pattern.get("color", [0, 60, 180])
            cdiff = pattern.get("cdiff", [200, 220, 255])
            wait_ms = pattern.get("wait_ms", 30)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            shimmer_sine_wave(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "shimmer_effect":
            color = pattern.get("color", [180, 80, 0])
            cdiff = pattern.get("cdiff", [255, 220, 120])
            wait_ms = pattern.get("wait_ms", 40)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            shimmer_effect(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "marquee_effect":
            color = pattern.get("color", [0, 0, 0])
            cdiff = pattern.get("cdiff", [255, 255, 255])
            wait_ms = pattern.get("wait_ms", 30)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            marquee_effect(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "aurora_drift":
            iterations = pattern["iterations"]
            wait_ms = pattern.get("wait_ms", 500)
            aurora_drift(iterations,wait_ms)
        elif str(pattern_type) == "cosmic_vortex":
            iterations = pattern.get("iterations", 100000)
            cosmic_vortex(iterations)
        elif str(pattern_type) == "serenity_flow":
            color = pattern.get("color", [0, 0, 0])
            cdiff = pattern.get("cdiff", [0, 0, 0])
            wait_ms = pattern.get("wait_ms", 30)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            serenity_flow(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "tranquil_drift":
            color = pattern.get("color", [0, 100, 200])
            cdiff = pattern.get("cdiff", [0, 180, 120])
            wait_ms = pattern.get("wait_ms", 50)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            tranquil_drift(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "digital_dreamscape":
            iterations = pattern["iterations"]
            wait_ms = pattern.get("wait_ms", 500)
            digital_dreamscape(iterations,wait_ms)
        elif str(pattern_type) == "thunderstorm":
            color = pattern.get("color", [0, 10, 30])
            cdiff = pattern.get("cdiff", [200, 210, 255])
            wait_ms = pattern.get("wait_ms", 2000)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            thunderstorm(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "joyful_celebration":
            color = pattern["color"]
            cdiff = pattern["cdiff"]
            wait_ms = pattern.get("wait_ms", 500)
            iterations = pattern.get("iterations", 100000)
            joyful_celebration(color, cdiff, wait_ms, iterations)
        elif str(pattern_type) == "marquee":
            color = pattern["color"]
            cdiff = pattern["cdiff"]
            wait_ms = pattern.get("wait_ms", 500)
            iterations = pattern.get("iterations", 100000)
            marquee(color,cdiff, wait_ms, iterations)
        elif str(pattern_type) == "ember_rise":
            color = pattern.get("color", [180, 40, 0])
            cdiff = pattern.get("cdiff", [255, 200, 60])
            wait_ms = pattern.get("wait_ms", 30)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            ember_rise(color, cdiff, wait_ms, iterations, direction)
        elif str(pattern_type) == "color_chase":
            color = pattern.get("color", [0, 100, 255])
            cdiff = pattern.get("cdiff", [255, 50, 0])
            wait_ms = pattern.get("wait_ms", 20)
            iterations = pattern.get("iterations", 9999999)
            direction = pattern.get("direction", 1)
            color_chase(color, cdiff, wait_ms, iterations, direction)
        else:
             solid_color([0,0,0])
run()

# list of functions in this file
# solid_color(color)
# color_wipe(color, wait_ms,direction)
# rainbow_cycle(iterations)
# sparkle(color, cdiff, wait_ms, iterations)
# beam(color, wait_ms, iterations,direction)
# rainbow_rotate(wait_ms,iterations)
# eye_look(color,wait_ms,iterations)
# lightning_strike()
# fireworks_simulation()
# fireworks_finale()
# shimmer_sine_wave()
# shimmer_effect()
# marquee_effect()
# aurora_drift()
# cosmic_vortex()
# serenity_flow()
# tranquil_drift()
# digital_dreamscape()
# thunderstorm()
# joyful_celebration()
