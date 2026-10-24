"""Rendering and visual presentation module for One More Jump.

Implements the Midnight Neon theme, parallax starfield, squash-and-stretch
player animations, glowing platform shaders, clean HUD with DSA checkpoint pips,
menus, pause overlay, and procedural sine-wave audio blips.
Reads state from Game without modifying any rules.
"""

import math
import random
from typing import List, Optional, Tuple
import pygame

from game import Game
from settings import (
    ACCENT_COLOR,
    BG_COLOR,
    BONUS_PULSE_DURATION,
    BUTTON_BG,
    BUTTON_BORDER,
    BUTTON_HOVER_BG,
    BUTTON_HOVER_BORDER,
    CHANCES_PER_RUN,
    CRUMBLE_COLOR,
    CRUMBLE_CRACK_COLOR,
    CRUMBLE_DELAY,
    CRUMBLE_TOP_COLOR,
    DEBRIS_DURATION,
    FLASH_COLOR,
    GRID_COLOR,
    HAZARD_COLOR,
    HAZARD_GLOW_COLOR,
    HEIGHT,
    MAX_FX_PARTICLES,
    MAX_POPUPS,
    NEAR_MISS_POPUP_DURATION,
    ORB_COLOR,
    ORB_CORE_COLOR,
    ORB_GLOW_COLOR,
    PAD_COLOR,
    PAD_GLOW_COLOR,
    PAD_HEIGHT,
    PAD_TOP_COLOR,
    PARTICLE_COLOR,
    PLATFORM_COLOR,
    PLATFORM_GLOW_COLOR,
    PLATFORM_TOP_COLOR,
    PLAYER_COLOR,
    PLAYER_EYE_COLOR,
    POPUP_CLOSE_COLOR,
    POPUP_DURATION,
    REWIND_FLASH_DURATION,
    SQUASH_DURATION,
    TEXT_COLOR,
    TEXT_MUTED,
    TITLE,
    WIDTH,
)

# --- Button Layout Geometry (Shared with main.py for hit-testing) ---
BUTTONS = {
    "play": pygame.Rect((WIDTH - 220) // 2, 400, 220, 52),
    "pause": pygame.Rect((WIDTH - 44) // 2, 14, 44, 32),
    "resume": pygame.Rect((WIDTH - 200) // 2, 280, 200, 50),
    "restart": pygame.Rect((WIDTH - 200) // 2, 348, 200, 50),
    "menu": pygame.Rect((WIDTH - 200) // 2, 416, 200, 50),
    "go_menu": pygame.Rect((WIDTH - 220) // 2, 468, 220, 52),
}


class SoundManager:
    """Generates procedural sine wave audio blips without external asset files."""

    def __init__(self) -> None:
        self.jump_sound: Optional[pygame.mixer.Sound] = None
        self.pad_sound: Optional[pygame.mixer.Sound] = None
        self.game_over_sound: Optional[pygame.mixer.Sound] = None
        self.orb_sound: Optional[pygame.mixer.Sound] = None
        self.risk_orb_sound: Optional[pygame.mixer.Sound] = None
        self.near_miss_sound: Optional[pygame.mixer.Sound] = None
        self.available: bool = False
        self._init_audio()

    def _init_audio(self) -> None:
        try:
            init_res = pygame.mixer.get_init()
            if not init_res:
                return
            freq, size, channels = init_res
            if size != -16:
                self.available = False
                return

            sound_defs = {
                "jump_sound": ([(587.33, 0.07)], 0.22),
                "pad_sound": ([(880.0, 0.10)], 0.25),
                "game_over_sound": ([(174.61, 0.35)], 0.28),
                "orb_sound": ([(988.0, 0.06), (1319.0, 0.09)], 0.22),
                "risk_orb_sound": ([(988.0, 0.06), (1319.0, 0.06), (1760.0, 0.10)], 0.24),
                "near_miss_sound": ([(523.25, 0.05), (783.99, 0.05), (1046.50, 0.08)], 0.22),
            }
            for attr, (notes, vol) in sound_defs.items():
                setattr(self, attr, self._make_tones(notes, vol, freq, channels))
            self.available = all(getattr(self, attr) is not None for attr in sound_defs)
        except Exception:
            self.available = False

    def _make_sine_wave(
        self, freq: float, duration: float, volume: float, sample_rate: int, channels: int
    ) -> Optional[pygame.mixer.Sound]:
        return self._make_tones([(freq, duration)], volume, sample_rate, channels)

    def _make_tones(
        self, notes: List[Tuple[float, float]], volume: float, sample_rate: int, channels: int
    ) -> Optional[pygame.mixer.Sound]:
        """Build a multi-note sound by concatenating sine buffers with exponential decay."""
        try:
            buffer = bytearray()
            for freq, duration in notes:
                num_samples = int(sample_rate * duration)
                for i in range(num_samples):
                    t = i / sample_rate
                    envelope = math.exp(-3.5 * t / duration)
                    sample = int(volume * 32767.0 * envelope * math.sin(2.0 * math.pi * freq * t))
                    sample_bytes = int(sample).to_bytes(2, byteorder="little", signed=True)
                    buffer += sample_bytes * channels
            return pygame.mixer.Sound(buffer=bytes(buffer))
        except Exception:
            return None

    def _play(self, sound: Optional[pygame.mixer.Sound]) -> None:
        if self.available and sound:
            try:
                sound.play()
            except Exception:
                pass

    def play_jump(self) -> None:
        self._play(self.jump_sound)

    def play_pad(self) -> None:
        self._play(self.pad_sound)

    def play_game_over(self) -> None:
        self._play(self.game_over_sound)

    def play_orb(self, risk: bool = False) -> None:
        self._play(self.risk_orb_sound if risk else self.orb_sound)

    def play_near_miss(self) -> None:
        self._play(self.near_miss_sound)


class Renderer:
    """Manages all visuals, UI presentation, animations, and sound triggers."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen: pygame.Surface = screen
        self.sounds: SoundManager = SoundManager()

        # Deterministic background starfield (40 dots pre-allocated once)
        rng = random.Random(42)
        self.particles: List[Tuple[float, float, int, float]] = [
            (rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT * 2), rng.randint(1, 3), rng.uniform(0.15, 0.45))
            for _ in range(40)
        ]

        # Typography with fallback to Pygame default font
        self.font_title = pygame.font.Font(None, 48)
        self.font_medium = pygame.font.Font(None, 26)
        self.font_small = pygame.font.Font(None, 20)
        self.font_score = pygame.font.Font(None, 34)

        # Reusable transparent surfaces
        self.pause_overlay_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.pause_overlay_surf.fill((11, 16, 38, 200))

        self.flash_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

        self.anim_time: float = 0.0

        # Visual effects state
        self.particles_fx: List[dict] = []
        self.popups: List[dict] = []
        self.rings: List[dict] = []
        self.text_cache: dict = {}
        self.bonus_pulse_timer: float = 0.0
        self.last_bonus_score: int = 0
        self.last_score: int = 0
        self.last_run_id: int = -1

    def draw_button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        text: str,
        hovered: bool,
    ) -> None:
        """Render a unified modern neon button with hover lighting and subtle scale."""
        draw_rect = rect.copy()
        if hovered:
            draw_rect = draw_rect.inflate(4, 2)
            bg = BUTTON_HOVER_BG
            border = BUTTON_HOVER_BORDER
            text_color = (255, 255, 255)
        else:
            bg = BUTTON_BG
            border = BUTTON_BORDER
            text_color = TEXT_COLOR

        pygame.draw.rect(surface, bg, draw_rect, border_radius=10)
        pygame.draw.rect(surface, border, draw_rect, width=2, border_radius=10)

        label = self.font_medium.render(text, True, text_color)
        label_rect = label.get_rect(center=draw_rect.center)
        surface.blit(label, label_rect)

    def _spawn_orb_fx(self, x: float, y: float, points: int, risk: bool) -> None:
        """Spawn expanding ring, burst particles, and score popup on orb collection."""
        self.rings.append({
            "x": x, "y": y, "radius_start": 8.0, "radius_end": 30.0,
            "duration": 0.3, "age": 0.0, "color": ORB_COLOR
        })
        if len(self.rings) > 16:
            self.rings.pop(0)

        num_particles = 12 if risk else 8
        for i in range(num_particles):
            angle = 2.0 * math.pi * i / num_particles + random.uniform(-0.2, 0.2)
            speed = random.uniform(60.0, 130.0)
            color = ORB_CORE_COLOR if i % 2 == 0 else ORB_COLOR
            self.particles_fx.append({
                "x": x, "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "duration": 0.4, "age": 0.0,
                "color": color, "size": random.randint(2, 4)
            })
        while len(self.particles_fx) > MAX_FX_PARTICLES:
            self.particles_fx.pop(0)

        self.popups.append({
            "x": x, "y": y, "text": f"+{points}",
            "base_color": ORB_COLOR, "duration": POPUP_DURATION, "age": 0.0,
            "is_near_miss": False
        })
        while len(self.popups) > MAX_POPUPS:
            self.popups.pop(0)

    def _spawn_near_miss_fx(self, x: float, y: float, points: int) -> None:
        """Spawn player ring and CLOSE! popup on near miss bonus award."""
        self.rings.append({
            "x": x, "y": y, "radius_start": 14.0, "radius_end": 34.0,
            "duration": 0.25, "age": 0.0, "color": HAZARD_COLOR
        })
        if len(self.rings) > 16:
            self.rings.pop(0)

        clamped_x = max(60.0, min(WIDTH - 60.0, x))
        self.popups.append({
            "x": clamped_x, "y": y - 10.0, "text": f"CLOSE! +{points}",
            "base_color": POPUP_CLOSE_COLOR, "duration": NEAR_MISS_POPUP_DURATION, "age": 0.0,
            "is_near_miss": True
        })
        while len(self.popups) > MAX_POPUPS:
            self.popups.pop(0)

    def _update_fx(self, dt: float) -> None:
        """Advance visual effects lifetimes and particle physics."""
        for r in self.rings:
            r["age"] += dt
        self.rings = [r for r in self.rings if r["age"] < r["duration"]]

        for p in self.particles_fx:
            p["age"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
        self.particles_fx = [p for p in self.particles_fx if p["age"] < p["duration"]]

        for pop in self.popups:
            pop["age"] += dt
        self.popups = [pop for pop in self.popups if pop["age"] < pop["duration"]]

    def render(self, game: Game, mouse_pos: Tuple[int, int], dt: float) -> None:
        """Render current game state based on active game mode."""
        self.anim_time += dt

        # Reset visual effects on menu or run restart
        current_run_id = getattr(game, "run_id", 0)
        if game.state == "menu" or current_run_id != self.last_run_id:
            self.particles_fx.clear()
            self.popups.clear()
            self.rings.clear()
            self.bonus_pulse_timer = 0.0
            self.last_bonus_score = 0
            self.last_score = 0
            self.last_run_id = current_run_id
        elif game.state == "playing":
            if game.bonus_score > self.last_bonus_score:
                self.bonus_pulse_timer = BONUS_PULSE_DURATION
            self.last_bonus_score = game.bonus_score
            self.last_score = game.score

        # Drain gameplay event queue
        events = list(game.events)
        game.events.clear()

        has_orb = False
        has_risk_orb = False
        has_near_miss = False

        for ev in events:
            ev_type = ev[0]
            if ev_type == "orb":
                _, ox, oy, pts, risk = ev
                if risk:
                    has_risk_orb = True
                else:
                    has_orb = True
                self._spawn_orb_fx(ox, oy, pts, risk)
            elif ev_type == "near_miss":
                _, px, py, pts, _ = ev
                has_near_miss = True
                self._spawn_near_miss_fx(px, py, pts)

        # Play at most one orb and one near-miss sound per frame
        if has_risk_orb:
            self.sounds.play_orb(risk=True)
        elif has_orb:
            self.sounds.play_orb(risk=False)

        if has_near_miss:
            self.sounds.play_near_miss()

        # Update effect aging only during active gameplay
        if game.state == "playing":
            if self.bonus_pulse_timer > 0.0:
                self.bonus_pulse_timer = max(0.0, self.bonus_pulse_timer - dt)
            self._update_fx(dt)

        # Audio triggers: clear one-shot flags immediately after playing
        if game.just_boosted:
            self.sounds.play_pad()
            game.just_boosted = False
            game.just_jumped = False
        elif game.just_jumped:
            self.sounds.play_jump()
            game.just_jumped = False
        if game.just_game_over:
            self.sounds.play_game_over()
            game.just_game_over = False

        # 1. Base Midnight Neon Background & Parallax Particles
        self._render_background(game.camera_y)

        # 2. In-World Gameplay Entities (Platforms, Pads, Spikes, Debris, Orbs, Player, Effects)
        if game.state in ("playing", "paused", "game_over"):
            self._render_platforms(game)
            self._render_pads(game)
            self._render_hazards(game)
            self._render_debris(game)
            self._render_orbs(game)
            self._render_player(game)
            self._render_effects(game.camera_y)

        # 3. Screen Flash on Rewind
        if game.rewind_flash_timer > 0.0:
            alpha = int(140 * (game.rewind_flash_timer / REWIND_FLASH_DURATION))
            self.flash_surf.fill((*FLASH_COLOR, alpha))
            self.screen.blit(self.flash_surf, (0, 0))

        # 4. State-Specific Overlays and Interfaces
        if game.state == "menu":
            self._render_menu(game, mouse_pos)
        elif game.state == "playing":
            self._render_hud(game, mouse_pos)
        elif game.state == "paused":
            self._render_hud(game, mouse_pos)
            self._render_pause_overlay(mouse_pos)
        elif game.state == "game_over":
            self._render_game_over(game, mouse_pos)

    def _render_background(self, camera_y: float) -> None:
        """Draw midnight navy fill, faint grid, and drifting parallax stars."""
        self.screen.fill(BG_COLOR)

        # Subtle vertical and horizontal grid lines drifting with camera
        grid_spacing = 60
        y_offset = int(-camera_y * 0.2) % grid_spacing
        for y in range(y_offset, HEIGHT, grid_spacing):
            pygame.draw.line(self.screen, GRID_COLOR, (0, y), (WIDTH, y), 1)
        for x in range(0, WIDTH, grid_spacing):
            pygame.draw.line(self.screen, GRID_COLOR, (x, 0), (x, HEIGHT), 1)

        # Parallax drifting particles
        for base_x, base_y, size, factor in self.particles:
            screen_y = int((base_y - camera_y * factor)) % HEIGHT
            screen_x = int(base_x)
            pygame.draw.circle(self.screen, PARTICLE_COLOR, (screen_x, screen_y), size)

    def _render_platforms(self, game: Game) -> None:
        """Draw platforms, distinguishing standard turquoise from fragile crumblers."""
        crumbler_map = {id(c.platform): c for c in game.crumblers}

        for p in game.platforms:
            screen_y = int(p.top - game.camera_y)
            # Culled offscreen check
            if screen_y + p.height < -10 or screen_y > HEIGHT + 10:
                continue

            c = crumbler_map.get(id(p))
            if c is not None:
                # Fragile crumbling platform
                shake = 0
                crack_width = 1
                if c.state == "crumbling":
                    shake = int(math.sin(self.anim_time * 50.0) * 2.0)
                    elapsed_ratio = max(0.0, min(1.0, 1.0 - (c.timer / CRUMBLE_DELAY)))
                    crack_width = int(1 + elapsed_ratio * 2.5)

                draw_x = p.left + shake
                plat_rect = pygame.Rect(draw_x, screen_y, p.width, p.height)

                # Subtle dark glow
                glow_rect = plat_rect.inflate(4, 2)
                pygame.draw.rect(self.screen, (15, 60, 65), glow_rect, border_radius=6)

                # Crumbler body
                pygame.draw.rect(self.screen, CRUMBLE_COLOR, plat_rect, border_radius=5)

                # Top rim highlight
                top_line = pygame.Rect(draw_x + 2, screen_y, p.width - 4, 2)
                pygame.draw.rect(self.screen, CRUMBLE_TOP_COLOR, top_line, border_radius=1)

                # 3-4 crack lines across the body
                c1_x = draw_x + int(p.width * 0.25)
                pygame.draw.line(self.screen, CRUMBLE_CRACK_COLOR, (c1_x, screen_y), (c1_x + 3, screen_y + p.height), width=crack_width)
                c2_x = draw_x + int(p.width * 0.55)
                pygame.draw.line(self.screen, CRUMBLE_CRACK_COLOR, (c2_x, screen_y), (c2_x - 4, screen_y + p.height), width=crack_width)
                c3_x = draw_x + int(p.width * 0.80)
                pygame.draw.line(self.screen, CRUMBLE_CRACK_COLOR, (c3_x, screen_y + 1), (c3_x + 2, screen_y + p.height), width=crack_width)
            else:
                # Normal platform
                plat_rect = pygame.Rect(p.left, screen_y, p.width, p.height)

                # Soft glow background
                glow_rect = plat_rect.inflate(6, 4)
                pygame.draw.rect(self.screen, PLATFORM_GLOW_COLOR, glow_rect, border_radius=6)

                # Platform body
                pygame.draw.rect(self.screen, PLATFORM_COLOR, plat_rect, border_radius=5)

                # Bright top surface highlight
                top_line_rect = pygame.Rect(p.left + 2, screen_y, p.width - 4, 3)
                pygame.draw.rect(self.screen, PLATFORM_TOP_COLOR, top_line_rect, border_radius=2)

    def _render_pads(self, game: Game) -> None:
        """Render bounce pads (spring coils and cap plates) resting atop platforms."""
        for pad in game.pads:
            screen_y = int(pad.rect.top - game.camera_y)
            if screen_y + pad.rect.height < -20 or screen_y > HEIGHT + 20:
                continue

            scale_h = 0.5 if pad.pressed_timer > 0.0 else 1.0
            cur_h = max(4, int(PAD_HEIGHT * scale_h))
            plat_top_screen = int(pad.platform.top - game.camera_y)
            spring_top_screen = plat_top_screen - cur_h
            pad_rect = pygame.Rect(pad.rect.left, spring_top_screen, pad.rect.width, cur_h)

            # Emerald glow backdrop
            glow_rect = pad_rect.inflate(4, 3)
            pygame.draw.rect(self.screen, PAD_GLOW_COLOR, glow_rect, border_radius=3)

            # Cap plate
            cap_h = 3
            cap_rect = pygame.Rect(pad_rect.left, pad_rect.top, pad_rect.width, cap_h)
            pygame.draw.rect(self.screen, PAD_COLOR, cap_rect, border_radius=2)
            pygame.draw.rect(self.screen, PAD_TOP_COLOR, pygame.Rect(pad_rect.left + 1, pad_rect.top, pad_rect.width - 2, 1))

            # Spring coil: zigzag segments
            coil_top = pad_rect.top + cap_h
            coil_bottom = plat_top_screen
            coil_h = coil_bottom - coil_top
            if coil_h > 2:
                seg_h = coil_h / 3.0
                pts = [
                    (pad_rect.left + 3, coil_top),
                    (pad_rect.right - 3, int(coil_top + seg_h)),
                    (pad_rect.left + 3, int(coil_top + 2 * seg_h)),
                    (pad_rect.right - 3, coil_bottom),
                ]
                pygame.draw.lines(self.screen, PAD_COLOR, False, pts, width=2)

    def _render_debris(self, game: Game) -> None:
        """Render disintegrating platform halves falling and fading into darkness."""
        for d in game.debris:
            t = d.age
            if t >= DEBRIS_DURATION:
                continue
            fade = max(0.0, 1.0 - (t / DEBRIS_DURATION))
            color = (
                int(BG_COLOR[0] + (CRUMBLE_COLOR[0] - BG_COLOR[0]) * fade),
                int(BG_COLOR[1] + (CRUMBLE_COLOR[1] - BG_COLOR[1]) * fade),
                int(BG_COLOR[2] + (CRUMBLE_COLOR[2] - BG_COLOR[2]) * fade),
            )
            drop_y = int(0.5 * 1400.0 * (t ** 2))
            screen_y = int(d.rect.top - game.camera_y) + drop_y
            if screen_y > HEIGHT + 40 or screen_y < -50:
                continue

            half_w = d.rect.width // 2
            drift = int(50.0 * t)
            left_rect = pygame.Rect(d.rect.left - drift, screen_y, half_w - 2, d.rect.height)
            right_rect = pygame.Rect(d.rect.left + half_w + 2 + drift, screen_y, half_w - 2, d.rect.height)
            pygame.draw.rect(self.screen, color, left_rect, border_radius=3)
            pygame.draw.rect(self.screen, color, right_rect, border_radius=3)

    def _render_hazards(self, game: Game) -> None:
        """Draw dangerous stationary platform spike strips."""
        for h in game.hazards:
            screen_y = int(h.rect.top - game.camera_y)
            # Skip off-screen spikes
            if screen_y + h.rect.height < -10 or screen_y > HEIGHT + 10:
                continue

            screen_x = h.rect.left
            # Subtle dark glow backdrop behind the spikes
            glow_rect = pygame.Rect(screen_x - 2, screen_y - 2, h.rect.width + 4, h.rect.height + 4)
            pygame.draw.rect(self.screen, HAZARD_GLOW_COLOR, glow_rect, border_radius=3)

            # Row of upward triangular spikes (approx 12 px wide each)
            num_spikes = max(1, h.rect.width // 12)
            spike_w = h.rect.width / num_spikes
            y_base = screen_y + h.rect.height
            y_apex = screen_y

            for i in range(num_spikes):
                x0 = screen_x + i * spike_w
                x1 = x0 + spike_w
                x_mid = (x0 + x1) / 2.0
                points = [(x0, y_base), (x_mid, y_apex), (x1, y_base)]
                pygame.draw.polygon(self.screen, HAZARD_COLOR, points)

    def _render_orbs(self, game: Game) -> None:
        """Render collectible bonus orbs with bobbing, glow pulse, core, and ring."""
        for orb in game.orbs:
            screen_y = int(orb.y - game.camera_y)
            if screen_y + orb.radius < -20 or screen_y - orb.radius > HEIGHT + 20:
                continue

            bob = int(math.sin(self.anim_time * 4.0 + orb.x * 0.05 + orb.y * 0.05) * 3.0)
            draw_y = screen_y + bob
            draw_x = int(orb.x)

            # Pulsing outer glow
            glow_pulse = int(math.sin(self.anim_time * 6.0 + orb.x * 0.1) * 2.0)
            pygame.draw.circle(self.screen, ORB_GLOW_COLOR, (draw_x, draw_y), int(orb.radius + 3 + glow_pulse))

            # Risk orbs get extra dangerous hazard ring
            if orb.risk:
                pygame.draw.circle(self.screen, HAZARD_COLOR, (draw_x, draw_y), int(orb.radius + 2), width=2)

            # Violet body
            pygame.draw.circle(self.screen, ORB_COLOR, (draw_x, draw_y), int(orb.radius))

            # White core
            pygame.draw.circle(self.screen, ORB_CORE_COLOR, (draw_x, draw_y), max(2, int(orb.radius * 0.45)))

            # Thin outer ring
            pygame.draw.circle(self.screen, (255, 255, 255), (draw_x, draw_y), int(orb.radius), width=1)

    def _render_effects(self, camera_y: float) -> None:
        """Render visual effect rings, burst particles, and rising text popups."""
        # Draw expanding rings
        for r in self.rings:
            progress = r["age"] / r["duration"]
            radius = int(r["radius_start"] + progress * (r["radius_end"] - r["radius_start"]))
            fade = max(0.0, 1.0 - progress)
            base_c = r["color"]
            c = (
                int(BG_COLOR[0] + (base_c[0] - BG_COLOR[0]) * fade),
                int(BG_COLOR[1] + (base_c[1] - BG_COLOR[1]) * fade),
                int(BG_COLOR[2] + (base_c[2] - BG_COLOR[2]) * fade),
            )
            screen_y = int(r["y"] - camera_y)
            if -50 <= screen_y <= HEIGHT + 50:
                pygame.draw.circle(self.screen, c, (int(r["x"]), screen_y), radius, width=2)

        # Draw burst particles
        for p in self.particles_fx:
            progress = p["age"] / p["duration"]
            fade = max(0.0, 1.0 - progress)
            base_c = p["color"]
            c = (
                int(BG_COLOR[0] + (base_c[0] - BG_COLOR[0]) * fade),
                int(BG_COLOR[1] + (base_c[1] - BG_COLOR[1]) * fade),
                int(BG_COLOR[2] + (base_c[2] - BG_COLOR[2]) * fade),
            )
            cur_size = max(1, int(p["size"] * (1.0 - progress * 0.5)))
            screen_y = int(p["y"] - camera_y)
            if -20 <= screen_y <= HEIGHT + 20:
                pygame.draw.circle(self.screen, c, (int(p["x"]), screen_y), cur_size)

        # Draw popups
        for pop in self.popups:
            progress = pop["age"] / pop["duration"]
            fade = max(0.0, 1.0 - progress)
            rise = 40.0 * (1.0 - (1.0 - progress) ** 2)
            screen_y = int(pop["y"] - camera_y - rise)
            if screen_y < -50 or screen_y > HEIGHT + 50:
                continue

            base_c = pop["base_color"]
            fade_step = int(fade * 10)
            ratio = fade_step / 10.0
            c = (
                int(BG_COLOR[0] + (base_c[0] - BG_COLOR[0]) * ratio),
                int(BG_COLOR[1] + (base_c[1] - BG_COLOR[1]) * ratio),
                int(BG_COLOR[2] + (base_c[2] - BG_COLOR[2]) * ratio),
            )

            size = "small"
            if pop["is_near_miss"]:
                size = "large" if pop["age"] < 0.12 else "medium"

            key = (pop["text"], c, size)
            if key not in self.text_cache:
                font = self.font_score if size == "large" else (self.font_medium if size == "medium" else self.font_small)
                self.text_cache[key] = font.render(pop["text"], True, c)

            surf = self.text_cache[key]
            rect = surf.get_rect(center=(int(pop["x"]), screen_y))
            self.screen.blit(surf, rect)

    def _render_player(self, game: Game) -> None:
        """Render character with landing squash and ascending stretch animations."""
        # Invisibility blink effect during invulnerability (alternating 0.1s intervals)
        if game.invuln_timer > 0.0:
            if int(game.invuln_timer * 10) % 2 == 1:
                return

        center_x = game.player_x + (game.player_width / 2.0)
        center_y = (game.player_y - game.camera_y) + (game.player_height / 2.0)

        # Squash on landing
        scale_x = 1.0
        scale_y = 1.0
        if game.squash_timer > 0.0:
            squash_factor = game.squash_timer / SQUASH_DURATION
            scale_x = 1.0 + (0.35 * squash_factor)
            scale_y = 1.0 - (0.28 * squash_factor)
        elif game.player_vy < -200.0:
            # Stretch upwards while rising fast
            stretch = min(0.30, abs(game.player_vy) / 2500.0)
            scale_x = 1.0 - (stretch * 0.5)
            scale_y = 1.0 + stretch

        draw_w = int(game.player_width * scale_x)
        draw_h = int(game.player_height * scale_y)
        draw_rect = pygame.Rect(0, 0, draw_w, draw_h)
        draw_rect.center = (int(center_x), int(center_y))

        # Draw glowing player body
        pygame.draw.rect(self.screen, PLAYER_COLOR, draw_rect, border_radius=12)

        # Eyes that glance in steering direction
        eye_offset_x = 0
        if game.player_vx > 20:
            eye_offset_x = 3
        elif game.player_vx < -20:
            eye_offset_x = -3

        left_eye_pos = (draw_rect.centerx - 6 + eye_offset_x, draw_rect.centery - 2)
        right_eye_pos = (draw_rect.centerx + 6 + eye_offset_x, draw_rect.centery - 2)
        pygame.draw.circle(self.screen, PLAYER_EYE_COLOR, left_eye_pos, 3)
        pygame.draw.circle(self.screen, PLAYER_EYE_COLOR, right_eye_pos, 3)

    def _render_hud(self, game: Game, mouse_pos: Tuple[int, int]) -> None:
        """Draw score, best score, pause button, and Second Chance stack pips."""
        # Top-left Total Score
        score_surf = self.font_score.render(str(game.total_score), True, TEXT_COLOR)
        self.screen.blit(score_surf, (20, 16))

        # Bonus score display underneath with violet orb icon
        bonus_icon_pos = (26, 54)
        pygame.draw.circle(self.screen, ORB_GLOW_COLOR, bonus_icon_pos, 7)
        pygame.draw.circle(self.screen, ORB_COLOR, bonus_icon_pos, 5)
        pygame.draw.circle(self.screen, ORB_CORE_COLOR, bonus_icon_pos, 2)

        bonus_str = f"+{game.bonus_score}"
        if self.bonus_pulse_timer > 0.0:
            pulse_t = self.bonus_pulse_timer / BONUS_PULSE_DURATION
            pulse_color = (
                int(ORB_COLOR[0] + (ORB_CORE_COLOR[0] - ORB_COLOR[0]) * pulse_t),
                int(ORB_COLOR[1] + (ORB_CORE_COLOR[1] - ORB_COLOR[1]) * pulse_t),
                int(ORB_COLOR[2] + (ORB_CORE_COLOR[2] - ORB_COLOR[2]) * pulse_t),
            )
            bonus_surf = self.font_medium.render(bonus_str, True, pulse_color)
            self.screen.blit(bonus_surf, (37, 44))
        else:
            bonus_surf = self.font_small.render(bonus_str, True, ORB_COLOR)
            self.screen.blit(bonus_surf, (37, 46))

        # Top-right Best
        best_label = self.font_small.render(f"BEST  {game.best_score}", True, TEXT_MUTED)
        self.screen.blit(best_label, (WIDTH - best_label.get_width() - 20, 20))

        # Top-center Pause Button
        pause_btn = BUTTONS["pause"]
        self.draw_button(self.screen, pause_btn, "||", pause_btn.collidepoint(mouse_pos))

        # Checkpoint Rewind Indicator (Second Chance Pips)
        pips_y = HEIGHT - 28
        label = self.font_small.render("SECOND CHANCE", True, TEXT_MUTED)
        self.screen.blit(label, (20, pips_y - 2))

        # Draw bounded chance slots: filled cyan circle for each remaining chance
        pip_start_x = 160
        num_chances = game.chances
        for i in range(CHANCES_PER_RUN):
            pip_x = pip_start_x + (i * 20)
            if i < num_chances:
                # Active remaining chance
                pygame.draw.circle(self.screen, ACCENT_COLOR, (pip_x, pips_y + 6), 6)
                pygame.draw.circle(self.screen, (255, 255, 255), (pip_x, pips_y + 6), 3)
            else:
                # Used chance slot
                pygame.draw.circle(self.screen, GRID_COLOR, (pip_x, pips_y + 6), 6, width=2)

    def _render_menu(self, game: Game, mouse_pos: Tuple[int, int]) -> None:
        """Render start menu with bobbing title, play button, and controls."""
        # Floating animated title
        bob = math.sin(self.anim_time * 3.0) * 8.0
        title_surf = self.font_title.render(TITLE, True, PLATFORM_COLOR)
        title_rect = title_surf.get_rect(center=(WIDTH // 2, 220 + int(bob)))
        self.screen.blit(title_surf, title_rect)

        # High score banner
        best_surf = self.font_medium.render(f"BEST SCORE: {game.best_score}", True, ACCENT_COLOR)
        best_rect = best_surf.get_rect(center=(WIDTH // 2, 290))
        self.screen.blit(best_surf, best_rect)

        # Play Button
        play_btn = BUTTONS["play"]
        self.draw_button(self.screen, play_btn, "PLAY", play_btn.collidepoint(mouse_pos))

        # Controls Guide
        c1 = self.font_small.render("A / D  or  ARROW KEYS to Steer", True, TEXT_MUTED)
        c2 = self.font_small.render("P to Pause   •   ESC to Quit", True, TEXT_MUTED)
        c3 = self.font_small.render("Collect orbs, skim spikes for bonus", True, PLATFORM_TOP_COLOR)
        self.screen.blit(c1, c1.get_rect(center=(WIDTH // 2, 540)))
        self.screen.blit(c2, c2.get_rect(center=(WIDTH // 2, 570)))
        self.screen.blit(c3, c3.get_rect(center=(WIDTH // 2, 605)))

    def _render_pause_overlay(self, mouse_pos: Tuple[int, int]) -> None:
        """Render semi-transparent pause modal with Resume, Restart, and Menu."""
        self.screen.blit(self.pause_overlay_surf, (0, 0))

        title = self.font_title.render("PAUSED", True, TEXT_COLOR)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 210)))

        self.draw_button(self.screen, BUTTONS["resume"], "RESUME", BUTTONS["resume"].collidepoint(mouse_pos))
        self.draw_button(self.screen, BUTTONS["restart"], "RESTART", BUTTONS["restart"].collidepoint(mouse_pos))
        self.draw_button(self.screen, BUTTONS["menu"], "MENU", BUTTONS["menu"].collidepoint(mouse_pos))

    def _render_game_over(self, game: Game, mouse_pos: Tuple[int, int]) -> None:
        """Render game over screen with scores, new best highlight, and buttons."""
        self.screen.blit(self.pause_overlay_surf, (0, 0))

        title = self.font_title.render("GAME OVER", True, ACCENT_COLOR)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 190)))

        score_text = self.font_score.render(f"SCORE: {game.total_score}", True, TEXT_COLOR)
        self.screen.blit(score_text, score_text.get_rect(center=(WIDTH // 2, 255)))

        breakdown_text = self.font_small.render(f"HEIGHT {game.score}  +  BONUS {game.bonus_score}", True, TEXT_MUTED)
        self.screen.blit(breakdown_text, breakdown_text.get_rect(center=(WIDTH // 2, 282)))

        if game.total_score >= game.best_score and game.total_score > 0:
            best_text = self.font_medium.render("NEW BEST!", True, PLATFORM_COLOR)
        else:
            best_text = self.font_medium.render(f"BEST: {game.best_score}", True, TEXT_MUTED)
        self.screen.blit(best_text, best_text.get_rect(center=(WIDTH // 2, 312)))

        self.draw_button(self.screen, BUTTONS["play"], "PLAY AGAIN", BUTTONS["play"].collidepoint(mouse_pos))
        self.draw_button(self.screen, BUTTONS["go_menu"], "MENU", BUTTONS["go_menu"].collidepoint(mouse_pos))
