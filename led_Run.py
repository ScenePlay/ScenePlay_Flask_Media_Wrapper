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


def fireworks_simulation(color=(255, 255, 255), cdiff=(255, 0, 0), wait_ms=5, iterations=5, fade_speed=0.01):
    """
    Simulate a fireworks effect on the LED strip.
    """
    for _ in range(iterations):
        # FIX 1: The upper bound for the start pixel must be num_pixels - 1.
        start_pixel = random.randint(0, num_pixels - 1)

        # Calculate a potential explosion center.
        potential_explosion_center = start_pixel + random.randint(5, 15)

        # FIX 2: Clamp the explosion_center to stay within the valid index range.
        explosion_center = min(potential_explosion_center, num_pixels - 1)

        # Launch the firework (lighting up trail pixels)
        for i in range(start_pixel, explosion_center):
            # This check is good practice, although our fixes make it less likely to be needed.
            if 0 <= i < num_pixels-1:
                pixels[i] = cdiff
                pixels.show()
                time.sleep(wait_ms / 1000.0)
                # Clear the trail behind to simulate movement
                pixels[i] = (0, 0, 0)

        # Explosion at the center
        if 0 <= explosion_center < num_pixels-1:
            pixels[explosion_center] = color
            pixels.show()
            time.sleep(wait_ms / 500.0)

        # Generate a random color for the fading sparks
        rndcolor = (colorRand(color[0], cdiff[0]), colorRand(color[1], cdiff[1]), colorRand(color[2], cdiff[2]))

        # Fade the explosion outward
        for radius in range(1, 10):
            for offset in [-radius, radius]:
                pixel_index = explosion_center + offset
                if 0 <= pixel_index < num_pixels-1:
                    # Calculate the faded color
                    fade_factor = 1 - (radius * fade_speed)
                    faded_color = tuple(max(0, int(c * fade_factor)) for c in rndcolor)
                    pixels[pixel_index] = faded_color
            pixels.show()
            time.sleep(wait_ms / 1000.0)

        # Clear the explosion area safely
        start_clear = max(0, explosion_center - 10)
        end_clear = min(num_pixels, explosion_center + 10)
        if end_clear > num_pixels-1:
            end_clear = num_pixels-1
        for i in range(start_clear, end_clear):
            pixels[i] = (0, 0, 0)
        pixels.show()
        time.sleep(wait_ms / 1000.0)

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
            if explosion_center > num_pixels-1:
                explosion_center = num_pixels-1
            pixels[explosion_center] = random_explosion_color
            pixels.show()
            time.sleep(wait_ms / 500.0)

            # Fade the explosion outward
            for radius in range(1, 10):
                for offset in [-radius, radius]:
                    pixel_index = explosion_center + offset
                    if 0 <= pixel_index < num_pixels-1:
                        pixels[pixel_index] = tuple(min(255, max(0, int(c * (1 - radius * fade_speed)))) for c in random_explosion_color)
                pixels.show()
                time.sleep(wait_ms / 1000.0)

        # Small delay before the next set of finales
        time.sleep(wait_ms / 500.0)

    # Clear the entire strip at the end of the finale
    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# fireworks_finale()  # Call this function to simulate a fireworks finale

def shimmer_sine_wave(duration=10, frequency=2, speed=0.05, color_change_speed=0.01):
    """
    Create a shimmering sine wave effect with shifting colors on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - frequency: Number of sine wave peaks across the LED strip.
    - speed: Speed at which the sine wave moves.
    - color_change_speed: Rate at which the color transitions over time.
    """
    start_time = time.time()
    
    while (time.time() - start_time) < duration:
        # Loop through all the pixels
        for i in range(num_pixels):
            # Calculate sine wave brightness (range 0 to 1)
            wave_value = (math.sin(2 * math.pi * frequency * i / num_pixels + time.time() * speed) + 1) / 2
            
            # Change the color gradually using a sine-based color transition
            r = int((math.sin(time.time() * color_change_speed) + 1) * 127.5)
            g = int((math.sin(time.time() * color_change_speed + 2) + 1) * 127.5)
            b = int((math.sin(time.time() * color_change_speed + 4) + 1) * 127.5)

            # Apply the sine wave effect to the brightness of the current color
            pixels[i] = (int(r * wave_value), int(g * wave_value), int(b * wave_value))

        # Update the LED strip
        pixels.show()
        time.sleep(0.01)  # Small delay for smooth animation

# Example usage:
# shimmer_sine_wave()  # Call this function to run the sine wave shimmer effect

def shimmer_effect(duration=10, speed=0.1, base_color=(255, 255, 255)):
    """
    Create a standard shimmer effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - speed: Delay between shimmer updates (smaller values = faster shimmer).
    - base_color: The base color to shimmer (default is white).
    """
    start_time = time.time()
    
    while (time.time() - start_time) < duration:
        # Loop through all the pixels and randomly adjust brightness
        for i in range(num_pixels):
            # Randomly pick a brightness level (from 50% to 100%)
            brightness_factor = random.uniform(0.5, 1.0)
            
            # Adjust the color by applying the brightness factor
            r = int(base_color[0] * brightness_factor)
            g = int(base_color[1] * brightness_factor)
            b = int(base_color[2] * brightness_factor)
            
            # Set the pixel color
            pixels[i] = (r, g, b)
        
        # Update the LED strip
        pixels.show()
        time.sleep(speed)  # Control the shimmer speed

    # Clear the strip after the shimmer effect
    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# shimmer_effect()  # Call this function to run the shimmer effect
def marquee_effect(foreground_color=(255, 255, 255), background_color=(0, 0, 0), block_size=5, speed=0.1, iterations=10):
    """
    Create a marquee effect on the LED strip.
    
    Parameters:
    - foreground_color: The color of the moving block of lights.
    - background_color: The color of the background (default is black).
    - block_size: The number of LEDs in the moving block.
    - speed: Delay between each movement (lower value = faster movement).
    - iterations: Number of times the block moves across the strip.
    """
    for _ in range(iterations):
        for i in range(num_pixels):
            # Set all pixels to background color
            pixels.fill(background_color)
            
            # Light up the block of pixels starting from the current position 'i'
            for j in range(block_size):
                if i + j < num_pixels:
                    pixels[i + j] = foreground_color
                else:
                    # Wrap around to the beginning
                    pixels[(i + j) % num_pixels] = foreground_color
            
            # Update the LED strip to show the current frame
            pixels.show()
            time.sleep(speed)

    # Clear the strip after the marquee effect
    pixels.fill(background_color)
    pixels.show()

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


def serenity_flow(duration=15, wave_speed=0.02, color_change_speed=0.005):
    """
    Create a calming 'Serenity Flow' effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - wave_speed: Speed of the flowing wave (lower value = slower movement).
    - color_change_speed: Speed at which the colors shift (lower value = slower color transition).
    """
    start_time = time.time()
    
    while (time.time() - start_time) < duration:
        current_time = time.time()

        # Loop through each pixel
        for i in range(num_pixels):
            # Calculate a smooth wave for brightness modulation (gentle sine wave pattern)
            wave_offset = math.sin((i / num_pixels) * 2 * math.pi + current_time * wave_speed)
            brightness = (wave_offset + 1) / 2  # Normalize the brightness to be between 0 and 1
            
            # Create a smooth color transition (soft colors, like a calming gradient)
            r = int((math.sin(current_time * color_change_speed) + 1) * 127.5)
            g = int((math.sin(current_time * color_change_speed + 2) + 1) * 127.5)
            b = int((math.sin(current_time * color_change_speed + 4) + 1) * 127.5)

            # Apply the brightness factor to the colors for each pixel
            pixels[i] = (int(r * brightness), int(g * brightness), int(b * brightness))

        # Update the LED strip
        pixels.show()
        time.sleep(0.01)  # Small delay for smooth animation

    # Clear the strip after the effect
    pixels.fill((0, 0, 0))
    pixels.show()

# Example usage:
# serenity_flow()  # Call this function to run the 'Serenity Flow' effect


def tranquil_drift(duration=20, speed=0.02, color_change_speed=0.003):
    """
    Create a 'Tranquil Drift' effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - speed: Speed of the gentle movement (lower value = slower and more calming).
    - color_change_speed: Rate at which the colors softly change over time.
    """
    start_time = time.time()
    
    while (time.time() - start_time) < duration:
        current_time = time.time()
        
        # Loop through all the pixels to create the slow, drifting effect
        for i in range(num_pixels):
            # Calculate smooth color transitions using a sine wave
            color_hue = (math.sin(current_time * color_change_speed + i * speed) + 1) / 2  # Range 0 to 1
            
            # Use a calming palette (focus on blues and greens)
            r = int((math.sin(color_hue * math.pi) + 1) * 127.5)  # Soft red transition
            g = int((math.cos(color_hue * math.pi / 2) + 1) * 127.5)  # Green softly fades in and out
            b = int((math.sin(color_hue * math.pi / 1.5) + 1) * 127.5)  # Gentle blue hues
            
            # Set the pixel color with smooth transitions
            pixels[i] = (r, g, b)
        
        # Update the LED strip
        pixels.show()
        time.sleep(0.05)  # Small delay for smoother animation

    # Clear the strip after the effect
    pixels.fill((0, 0, 0))
    pixels.show()

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


def lightning_strike(duration=10, min_strike_delay=0.5, max_strike_delay=2, min_strike_length=5, max_strike_length=20):
    """
    Create a 'Lightning Strike' effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - min_strike_delay: Minimum time between lightning strikes (in seconds).
    - max_strike_delay: Maximum time between lightning strikes (in seconds).
    - min_strike_length: Minimum number of pixels affected by a lightning strike.
    - max_strike_length: Maximum number of pixels affected by a lightning strike.
    """
    start_time = time.time()

    while (time.time() - start_time) < duration:
        # Randomly select the delay before the next lightning strike
        strike_delay = random.uniform(min_strike_delay, max_strike_delay)
        time.sleep(strike_delay)

        # Randomly determine the location and length of the lightning strike
        strike_start = random.randint(0, num_pixels - 1)
        strike_length = random.randint(min_strike_length, max_strike_length)
        strike_end = min(strike_start + strike_length, num_pixels - 1)

        # Generate the lightning strike (bright white flash)
        for i in range(strike_start, strike_end):
            # Lightning flash with varying intensity
            intensity = random.uniform(0.8, 1.0)
            pixels[i] = (int(255 * intensity), int(255 * intensity), int(255 * intensity))
        pixels.show()

        # Short flash duration
        time.sleep(0.1)

        # Afterglow effect - dimming the lightning slowly
        for step in range(5):
            for i in range(strike_start, strike_end):
                current_color = pixels[i]
                pixels[i] = (max(0, int(current_color[0] * 0.7)), max(0, int(current_color[1] * 0.7)), max(0, int(current_color[2] * 0.7)))
            pixels.show()
            time.sleep(0.05)

        # Clear the strike after the afterglow fades
        for i in range(strike_start, strike_end):
            pixels[i] = (0, 0, 0)
        pixels.show()

# Example usage:
# lightning_strike()  # Call this function to run the 'Lightning Strike' effect


def thunderstorm(iterations=30, min_strike_delay=1, max_strike_delay=3, min_strike_length=5, max_strike_length=20, rain_intensity=0.05):
    """
    Create a 'Thunderstorm' effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - min_strike_delay: Minimum time between lightning strikes (in seconds).
    - max_strike_delay: Maximum time between lightning strikes (in seconds).
    - min_strike_length: Minimum number of pixels affected by a lightning strike.
    - max_strike_length: Maximum number of pixels affected by a lightning strike.
    - rain_intensity: Rate of fading to simulate rain.
    """
    start_time = time.time()
    
    while (time.time() - start_time) < iterations:
        # Ambient rainfall effect
        for i in range(num_pixels):
            if random.random() < rain_intensity:
                pixels[i] = (0, 0, 255)  # Blue color for rain
            else:
                pixels[i] = (0, 0, 0)  # Off
        pixels.show()
        
        # Randomly select the delay before the next lightning strike
        strike_delay = random.uniform(min_strike_delay, max_strike_delay)
        time.sleep(strike_delay)

        # Randomly determine the location and length of the lightning strike
        strike_start = random.randint(0, num_pixels - 1)
        strike_length = random.randint(min_strike_length, max_strike_length)
        strike_end = min(strike_start + strike_length, num_pixels - 1)

        # Generate the lightning strike (bright white flash)
        for i in range(strike_start, strike_end):
            intensity = random.uniform(0.8, 1.0)
            pixels[i] = (int(255 * intensity), int(255 * intensity), int(255 * intensity))
        pixels.show()

        # Short flash duration
        time.sleep(0.1)

        # Afterglow effect - dimming the lightning slowly
        for step in range(5):
            for i in range(strike_start, strike_end):
                current_color = pixels[i]
                pixels[i] = (max(0, int(current_color[0] * 0.7)), max(0, int(current_color[1] * 0.7)), max(0, int(current_color[2] * 0.7)))
            pixels.show()
            time.sleep(0.05)

        # Clear the strike after the afterglow fades
        for i in range(strike_start, strike_end):
            pixels[i] = (0, 0, 0)
        pixels.show()

# Example usage:
# thunderstorm()  # Call this function to run the 'Thunderstorm' effect


def joyful_celebration(duration=30, pulse_speed=0.1, chase_speed=0.05, confetti_probability=0.02):
    """
    Create a 'Joyful Celebration' light show effect on the LED strip.
    
    Parameters:
    - duration: Duration of the effect in seconds.
    - pulse_speed: Speed of the color pulsing effect.
    - chase_speed: Speed of the chasing lights effect.
    - confetti_probability: Chance of confetti flash during the effect.
    """
    start_time = time.time()
    colors = [(255, 0, 0), (255, 165, 0), (255, 255, 0), (0, 255, 0), (0, 0, 255), (75, 0, 130), (238, 130, 238)]  # Rainbow colors
    
    while (time.time() - start_time) < duration:
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

        # Confetti effect
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
    for z in range(iterations):
        for i in range(num_pixels):
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
            lightning_strike()
        elif str(pattern_type) == "fireworks_simulation":
            color = pattern["color"]
            cdiff = pattern["cdiff"]
            wait_ms = pattern.get("wait_ms", 500)
            iterations = pattern.get("iterations", 100)
            fireworks_simulation(color, cdiff, wait_ms, iterations)
        elif str(pattern_type) == "fireworks_finale":
            fireworks_finale()
        elif str(pattern_type) == "shimmer_sine_wave":
            shimmer_sine_wave()
        elif str(pattern_type) == "shimmer_effect ":
            shimmer_effect()
        elif str(pattern_type) == "marquee_effect":
            marquee_effect()
        elif str(pattern_type) == "aurora_drift":
            iterations = pattern["iterations"]
            wait_ms = pattern.get("wait_ms", 500)
            aurora_drift(iterations,wait_ms)
        elif str(pattern_type) == "cosmic_vortex":
            iterations = pattern.get("iterations", 100000)
            cosmic_vortex(iterations)
        elif str(pattern_type) == "serenity_flow":
            serenity_flow()
        elif str(pattern_type) == "tranquil_drift":
            tranquil_drift()
        elif str(pattern_type) == "digital_dreamscape":
            iterations = pattern["iterations"]
            wait_ms = pattern.get("wait_ms", 500)
            digital_dreamscape(iterations,wait_ms)
        elif str(pattern_type) == "lightning_strike":
            lightning_strike()
        elif str(pattern_type) == "thunderstorm":
            iterations = pattern["iterations"]
            thunderstorm(iterations)
        elif str(pattern_type) == "joyful_celebration":
            joyful_celebration()
        elif str(pattern_type) == "marquee":
            color = pattern["color"]
            cdiff = pattern["cdiff"]
            wait_ms = pattern.get("wait_ms", 500)
            iterations = pattern.get("iterations", 100000)
            marquee(color,cdiff, wait_ms, iterations)
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
