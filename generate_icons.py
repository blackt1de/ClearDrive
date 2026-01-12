"""
Generate PWA icons for ClearDrive
Run: python generate_icons.py
Requires: pip install pillow
"""

from PIL import Image, ImageDraw
import os

# Icon sizes needed for PWA
sizes = [72, 96, 128, 144, 152, 167, 180, 192, 384, 512]

# Create icons directory if it doesn't exist
os.makedirs('icons', exist_ok=True)

def create_icon(size):
    """Create a ClearDrive icon at the specified size."""
    # Create image with transparent background
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background - dark with rounded corners (simulate with circle)
    padding = int(size * 0.05)
    corner_radius = int(size * 0.2)

    # Draw rounded rectangle background
    draw.rounded_rectangle(
        [padding, padding, size - padding, size - padding],
        radius=corner_radius,
        fill=(10, 15, 10, 255)  # Dark green-black
    )

    # Draw green gradient circle (logo)
    center = size // 2
    logo_radius = int(size * 0.25)

    # Outer glow
    for i in range(10, 0, -1):
        alpha = int(40 * (1 - i/10))
        glow_radius = logo_radius + int(size * 0.02 * i)
        draw.ellipse(
            [center - glow_radius, center - glow_radius,
             center + glow_radius, center + glow_radius],
            fill=(34, 197, 94, alpha)
        )

    # Main green circle
    draw.ellipse(
        [center - logo_radius, center - logo_radius,
         center + logo_radius, center + logo_radius],
        fill=(34, 197, 94, 255)  # Green
    )

    # Inner lighter circle for depth
    inner_radius = int(logo_radius * 0.6)
    draw.ellipse(
        [center - inner_radius, center - inner_radius - int(size * 0.02),
         center + inner_radius, center + inner_radius - int(size * 0.02)],
        fill=(74, 222, 128, 255)  # Lighter green
    )

    # Car silhouette (simple)
    car_width = int(size * 0.3)
    car_height = int(size * 0.12)
    car_left = center - car_width // 2
    car_top = center - car_height // 2

    # Car body
    draw.rounded_rectangle(
        [car_left, car_top, car_left + car_width, car_top + car_height],
        radius=int(size * 0.02),
        fill=(255, 255, 255, 255)
    )

    # Car roof
    roof_width = int(car_width * 0.5)
    roof_height = int(size * 0.08)
    roof_left = center - roof_width // 2
    roof_top = car_top - roof_height + int(size * 0.02)
    draw.rounded_rectangle(
        [roof_left, roof_top, roof_left + roof_width, car_top + int(size * 0.02)],
        radius=int(size * 0.02),
        fill=(255, 255, 255, 255)
    )

    # Wheels
    wheel_radius = int(size * 0.03)
    wheel_y = car_top + car_height - wheel_radius
    draw.ellipse(
        [car_left + int(car_width * 0.2) - wheel_radius, wheel_y - wheel_radius,
         car_left + int(car_width * 0.2) + wheel_radius, wheel_y + wheel_radius],
        fill=(20, 20, 20, 255)
    )
    draw.ellipse(
        [car_left + int(car_width * 0.8) - wheel_radius, wheel_y - wheel_radius,
         car_left + int(car_width * 0.8) + wheel_radius, wheel_y + wheel_radius],
        fill=(20, 20, 20, 255)
    )

    return img

# Generate all icon sizes
for size in sizes:
    icon = create_icon(size)
    filename = f'icons/icon-{size}.png'
    icon.save(filename, 'PNG')
    print(f'Created {filename}')

print('\nAll icons generated successfully!')
print('Icons are in the "icons" folder.')
