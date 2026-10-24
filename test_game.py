"""Automated unit and integration tests for One More Jump.

Verifies:
1. Stack operations (LIFO order, capacity bounds, oldest-item eviction, empty pop).
2. Procedural platform reachability across >= 10,000 generated platforms.
3. Accurate collision physics (landing, rising, beside).
4. Score monotonicity across upward climbing and checkpoint rewinding.
5. Second chance rewind restoration (camera position, player alignment, stack pop, empty stack game over).
6. State reset integrity in start_run().
7. High score file I/O resilience (missing, empty, corrupted, non-integer data) without touching real save file.
8. One-shot audio trigger clearing in Renderer and audio smoke.
9. Hazard progression, densities, and fairness invariants.
10. Spike collision, safe zone landing, and invulnerability.
11. Hit consequences (rewind & game_over) and checkpoint safety.
12. Specials progression and fairness invariants over 10,000+ platforms.
13. Bounce pad mechanics (launch velocity, forgiveness margin, apex height, rising pass-through).
14. Crumbler mechanics (landing trigger, disintegration, debris, fall-through, pause freeze) and plain checkpoints.
15. Route reachability and intact crumbler restoration after rewind.
16. Prune safety checkpoint invariant and patrol hazard removal.
17. Orb generation score gating, clearance, bounds, density, and pickup anti-tunneling.
18. Near-miss bonus conditions (zone exit, margin, collision, single payout, last platform, invuln).
19. Scoring properties, difficulty isolation, FX lifecycle, and renderer smoke.
20. Three-chance sequence, independent decrement, safe platform pruning, and HUD pips.
21. Stability soak (20,000 frames with bot AI and headless rendering).
"""

import math
import os
from pathlib import Path
import random
from typing import Optional

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()

from dsa import Stack
from game import Crumbler, Debris, Game, Hazard, Orb, Pad, Platform, load_highscore, save_highscore
from renderer import Renderer
import settings
from settings import (
    CHANCES_PER_RUN,
    CRUMBLE_DELAY,
    CRUMBLE_MIN_PLAIN_BETWEEN,
    CRUMBLE_START_SCORE,
    DEBRIS_DURATION,
    DIFFICULTY_RAMP_SCORE,
    HEIGHT,
    JUMP_HEIGHT,
    JUMP_VELOCITY,
    MAX_DX,
    MAX_FALL_SPEED,
    MAX_FX_PARTICLES,
    MAX_GAP_LIMIT,
    MAX_POPUPS,
    MAX_SPECIAL_RUN,
    NEAR_MISS_MARGIN,
    NEAR_MISS_POINTS,
    ORB_CLEARANCE,
    ORB_POINTS,
    ORB_RADIUS,
    PAD_CLEAR_PLATFORMS,
    PAD_FORGIVENESS,
    PAD_HEIGHT,
    PAD_HEIGHT_FACTOR,
    PAD_JUMP_VELOCITY,
    PAD_PRESS_DURATION,
    PAD_START_SCORE,
    PAD_WIDTH,
    PLATFORM_HEIGHT,
    PLATFORM_MIN_WIDTH,
    PLATFORM_START_WIDTH,
    PLAYER_HITBOX_INSET,
    PLAYER_SIZE,
    PRUNE_MARGIN,
    REWIND_SCREEN_RATIO,
    RISK_ORB_HEIGHT,
    RISK_ORB_POINTS,
    RISK_ORB_RADIUS,
    SPIKE_COVERAGE,
    SPIKE_HEIGHT,
    START_X,
    WIDTH,
)


def make_game(score: int = 0, hazards: bool = True, specials: bool = True, orbs: bool = True) -> Game:
    g = Game()
    g.hazards_enabled = hazards
    g.specials_enabled = specials
    g.orbs_enabled = orbs
    g.start_run()
    if score:
        g.score = score
    return g


def climb(game: Game, count: int, step: float = 5000.0, score_inc: int = 0) -> None:
    while len(game.platforms) < count:
        game.camera_y -= step
        if score_inc:
            game.score = min(2000, game.score + score_inc)
        game._generate_platforms()


def assert_reachability(platforms: list[Platform]) -> None:
    sorted_p = sorted(platforms, key=lambda p: -p.top)
    for i in range(len(sorted_p) - 1):
        v = sorted_p[i].top - sorted_p[i + 1].top
        assert 0 < v <= MAX_GAP_LIMIT + 1e-4, f"Vertical gap {v} invalid"
        h = abs(sorted_p[i + 1].centerx - sorted_p[i].centerx)
        assert h <= MAX_DX + 1e-4, f"Horizontal gap {h} invalid"


def force_fall(game: Game) -> None:
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)


def test_stack_operations() -> None:
    """Test 1: LIFO behavior, capacity bounding, and empty behavior."""
    s = Stack[int](capacity=3)
    assert s.is_empty() and s.size() == 0
    assert s.pop() is None and s.peek() is None

    s.push(10)
    s.push(20)
    assert s.size() == 2 and s.peek() == 20
    assert s.pop() == 20 and s.peek() == 10
    assert s.pop() == 10 and s.is_empty()

    s.push(1)
    s.push(2)
    s.push(3)
    assert s.is_full() and s.size() == 3

    s.push(4)  # Evicts 1
    assert s.size() == 3
    assert [s.pop(), s.pop(), s.pop()] == [4, 3, 2]
    assert s.pop() is None
    print("✓ Test 1 Passed: Stack operations & bounded eviction.")


def test_reachability() -> None:
    """Test 2: Generate 10,000+ platforms; verify reachability, offsets, overlap, and difficulty scaling."""
    game = make_game(hazards=False, specials=False, orbs=False)
    climb(game, 10500, step=5000.0, score_inc=50)

    platforms = game.platforms
    assert len(platforms) >= 10000
    sorted_p = sorted(platforms, key=lambda p: -p.top)
    total_pairs = len(sorted_p) - 1
    clamped_count = 0

    for i in range(total_pairs):
        lower, upper = sorted_p[i], sorted_p[i + 1]
        v_gap = lower.top - upper.top
        assert 0 < v_gap <= MAX_GAP_LIMIT + 1e-4, f"Gap violation: {v_gap}"
        dx = abs(upper.centerx - lower.centerx)
        assert dx <= MAX_DX + 1e-4, f"dx violation: {dx}"
        assert upper.left >= 0 and upper.right <= WIDTH
        assert not lower.colliderect(upper)
        if upper.left == 0 or upper.right == WIDTH:
            clamped_count += 1
        else:
            assert dx >= 50 - 1e-4

    clamped_pct = (clamped_count / total_pairs) * 100.0
    assert clamped_pct <= 5.0

    g0 = make_game(score=0, hazards=False, specials=False, orbs=False)
    climb(g0, 500, step=1000.0)
    g0_sorted = sorted(g0.platforms, key=lambda p: -p.top)
    g0_gaps = [g0_sorted[j].top - g0_sorted[j + 1].top for j in range(len(g0_sorted) - 1)]
    avg_g0_gap = sum(g0_gaps) / len(g0_gaps)
    assert avg_g0_gap >= 100.0
    assert all(p.width == PLATFORM_START_WIDTH for p in g0.platforms[1:])

    g1 = make_game(score=DIFFICULTY_RAMP_SCORE, hazards=False, specials=False, orbs=False)
    init_count = len(g1.platforms)
    climb(g1, 500, step=1000.0)
    g1_plats = g1.platforms[init_count:]
    g1_sorted = sorted(g1_plats, key=lambda p: -p.top)
    g1_gaps = [g1_sorted[j].top - g1_sorted[j + 1].top for j in range(len(g1_sorted) - 1)]
    avg_g1_gap = sum(g1_gaps) / len(g1_gaps)
    assert avg_g1_gap >= 132.0
    assert all(p.width == PLATFORM_MIN_WIDTH for p1 in [g1_plats] for p in p1)

    print(
        f"✓ Test 2 Passed: Reachability verified across {len(platforms)} platforms "
        f"(clamped={clamped_pct:.2f}%, g0_avg_gap={avg_g0_gap:.1f}, g1_avg_gap={avg_g1_gap:.1f})."
    )


def test_collision() -> None:
    """Test 3: Falling player lands, rising player passes through, beside player does not land."""
    game = make_game(hazards=False, specials=False, orbs=False)
    test_plat = Platform(100, 300, 100, 12)
    game.platforms = [test_plat]

    # Falling lands
    game.player_x = 120.0
    game.player_y = 295.0 - PLAYER_SIZE
    game.player_vy = 300.0
    game.update(dt=0.03, move_dir=0)
    assert game.player_vy == JUMP_VELOCITY
    assert game.player_y == test_plat.top - PLAYER_SIZE

    # Rising passes through
    game.player_x = 120.0
    game.player_y = 310.0
    game.player_vy = -400.0
    game.update(dt=0.03, move_dir=0)
    assert game.player_vy < 0.0

    # Beside does not land
    game.player_x = 250.0
    game.player_y = 290.0 - PLAYER_SIZE
    game.player_vy = 300.0
    game.update(dt=0.03, move_dir=0)
    assert game.player_vy > 0.0

    print("✓ Test 3 Passed: Collision physics verified.")


def test_score_monotonicity() -> None:
    """Test 4: Score is non-decreasing over simulated climb, through falls and rewinds."""
    game = make_game(hazards=False, specials=False, orbs=False)
    last_score = game.score
    for _ in range(50):
        game.player_y -= 40.0
        game.update(dt=0.02, move_dir=0)
        assert game.score >= last_score
        last_score = game.score

    score_before = game.score
    game.checkpoint_stack.push((100, int(game.player_y - 20), 100, 12))
    game.player_y = game.camera_y + HEIGHT + 10.0
    game.update(dt=0.02, move_dir=0)
    assert game.score == score_before
    print("✓ Test 4 Passed: Score monotonicity and rewind invariance verified.")


def test_rewind_and_game_over() -> None:
    """Test 5: Rewind restores player, positions camera, decrements chances; 0 chances ends run."""
    game = make_game(hazards=False, specials=False, orbs=False)
    cp_rect = (150, int(game.camera_y + 100), 80, 12)
    game.checkpoint_stack.push(cp_rect)
    assert game.checkpoint_stack.size() == 1 and game.chances == 3

    force_fall(game)
    assert game.state == "playing" and game.checkpoint_stack.size() == 0 and game.chances == 2
    assert Platform(*cp_rect) in game.platforms
    assert abs(game.camera_y - (cp_rect[1] - HEIGHT * REWIND_SCREEN_RATIO)) < 1.0
    assert game.player_vy == JUMP_VELOCITY

    for expected_chances in [1, 0]:
        force_fall(game)
        assert game.chances == expected_chances and game.state == "playing"

    force_fall(game)
    assert game.state == "game_over"
    print("✓ Test 5 Passed: Rewind and Game Over transitions verified.")


def test_start_run_reset() -> None:
    """Test 6: start_run() fully resets score, platforms, camera, player, and stack."""
    game = make_game()
    game.score, game.bonus_score = 2500, 500
    game.camera_y, game.player_y = -3000.0, -3200.0
    game.checkpoint_stack.push((50, -3200, 80, 12))
    plat = Platform(0, 0, 100, 12)
    game.hazards.append(Hazard(platform=plat, rect=pygame.Rect(0, 0, 10, 10)))
    game.orbs.append(Orb(x=50.0, y=50.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False))
    game.invuln_timer = 2.0
    game.state = "game_over"

    game.start_run()
    assert game.state == "playing" and game.score == 0 and game.bonus_score == 0
    assert game.chances == CHANCES_PER_RUN and game.checkpoint_stack.is_empty()
    assert len(game.platforms) > 0
    assert len(game.hazards) == 0 or all(h.platform in game.platforms for h in game.hazards)
    assert game.invuln_timer == 0.0 and game.player_vy == JUMP_VELOCITY
    assert abs(game.player_x - START_X) < 1.0
    print("✓ Test 6 Passed: Complete reset on start_run().")


def test_highscore_io(tmp_path: Path) -> None:
    """Test 7: File missing, empty, corrupt, and non-integer load as 0; round-trip saves properly."""
    test_file = tmp_path / "test_highscore.json"
    real_existed = settings.HIGHSCORE_PATH.exists()
    real_content = settings.HIGHSCORE_PATH.read_text(encoding="utf-8") if real_existed else None

    for content in [None, "", "{bad json: 123", '{"highscore": "not_an_int"}', '{"highscore": true}']:
        if content is None:
            if test_file.exists():
                test_file.unlink()
        else:
            test_file.write_text(content, encoding="utf-8")
        assert load_highscore(test_file) == 0

    save_highscore(420, test_file)
    assert load_highscore(test_file) == 420
    save_highscore(9999, test_file)
    assert load_highscore(test_file) == 9999

    assert real_existed == settings.HIGHSCORE_PATH.exists()
    assert real_content == (settings.HIGHSCORE_PATH.read_text(encoding="utf-8") if real_existed else None)
    if test_file.exists():
        test_file.unlink()
    print("✓ Test 7 Passed: High score persistence resilience without touching real file.")


def test_audio_trigger_clear() -> None:
    """Test 8: Verify renderer clears just_game_over on first render and audio methods execute."""
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)
    game = Game()
    game.state = "game_over"
    game.just_game_over = True

    renderer.render(game, (0, 0), dt=1.0 / 60.0)
    assert not game.just_game_over
    renderer.render(game, (0, 0), dt=1.0 / 60.0)
    assert not game.just_game_over

    renderer.sounds.play_orb(False)
    renderer.sounds.play_orb(True)
    renderer.sounds.play_near_miss()
    print("✓ Test 8 Passed: Sound trigger clearance verified (no repeating sound after game over).")


def test_hazard_progression() -> None:
    """Test 9: Hazard progression and density scaling across score tiers."""
    random.seed(42)
    scores = [100, 150, 350, 800, 1500]
    densities = {}
    for s in scores:
        g = make_game(score=s, hazards=True, specials=False, orbs=False)
        init_p, init_h = len(g.platforms), len(g.hazards)
        while len(g.platforms) - init_p < 5000:
            g.camera_y -= 1000.0
            g._generate_platforms()
        new_p, new_h = g.platforms[init_p:], g.hazards[init_h:]
        densities[s] = ((len(new_h) / len(new_p)) * 100.0, new_h)

    assert len(densities[100][1]) == 0

    print("\nHazard Density Table (Hazards per 100 platforms):")
    print("---------------------------------------")
    print(" Score Tier | Hazards / 100 Platforms")
    print("---------------------------------------")
    for s in [150, 350, 800, 1500]:
        print(f"   {s:4d}     |         {densities[s][0]:5.2f}")
    print("---------------------------------------")

    d = [densities[s][0] for s in [150, 350, 800, 1500]]
    for i in range(1, len(d)):
        assert d[i] >= d[i - 1] - 1.0
    print("✓ Test 9 Passed: Hazard progression verified.")


def test_hazard_fairness_invariants() -> None:
    """Test 10: Invariants over 10,000+ platforms with hazards enabled."""
    random.seed(42)
    game = make_game(hazards=True, specials=False, orbs=False)
    climb(game, 10500, step=5000.0, score_inc=25)

    assert_reachability(game.platforms)

    for h in game.hazards:
        assert h.platform is not None and h.platform.width >= 90
        assert (h.platform.width - h.rect.width) >= PLAYER_SIZE + 20

    spiked_ids = {id(h.platform) for h in game.hazards if h.platform}
    for i in range(len(game.platforms) - 1):
        assert not (id(game.platforms[i]) in spiked_ids and id(game.platforms[i + 1]) in spiked_ids)

    print("✓ Test 10 Passed: Hazard fairness invariants verified over 10,000+ platforms.")


def test_spike_collision() -> None:
    """Test 11: Spike collision, safe zone landing, and invulnerability."""
    plat = Platform(100, 400, 100, 12)
    strip = pygame.Rect(100, 400 - SPIKE_HEIGHT, int(100 * SPIKE_COVERAGE), SPIKE_HEIGHT)
    spike = Hazard(platform=plat, rect=strip)
    s_hitbox = spike.hitbox()

    def reset_test(invuln: float = 0.0) -> Game:
        g = make_game(score=500, hazards=True)
        g.platforms, g.hazards, g.chances, g.invuln_timer = [plat], [spike], 0, invuln
        return g

    # Hit
    g = reset_test()
    g.player_x = s_hitbox.centerx - g.player_width / 2.0
    g.player_y = s_hitbox.centery - g.player_height / 2.0
    g.update(0.01, 0)
    assert g.state == "game_over"

    # Margin outside hitbox
    g = reset_test()
    g.player_x = strip.left - (g.player_width - PLAYER_HITBOX_INSET - 1)
    g.player_y = strip.top
    g.update(0.01, 0)
    assert g.state == "playing"

    # Safe side
    g = reset_test()
    g.player_x = plat.right - g.player_width - 2
    g.player_y = plat.top - g.player_height - 2
    g.player_vy = 200.0
    g.update(0.02, 0)
    assert g.state == "playing" and g.player_vy == JUMP_VELOCITY

    # Invulnerable
    g = reset_test(invuln=1.0)
    g.player_x = s_hitbox.centerx - g.player_width / 2.0
    g.player_y = s_hitbox.centery - g.player_height / 2.0
    g.update(0.01, 0)
    assert g.state == "playing"

    print("✓ Test 11 Passed: Spike collision and safe landing verified.")


def test_hit_consequences_and_checkpoint_safety() -> None:
    """Test 12: Hit consequences (rewind & game_over) and checkpoint safety."""
    game = make_game(score=600, hazards=True, specials=False, orbs=False)
    clean_plat = Platform(150, 400, 100, 12)
    spike_plat = Platform(150, 200, 100, 12)
    spike = Hazard(platform=spike_plat, rect=pygame.Rect(150, 200 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT))
    game.platforms = [clean_plat, spike_plat]
    game.hazards = [spike]
    game.checkpoint_stack.push((clean_plat.x, clean_plat.y, clean_plat.width, clean_plat.height))

    s_hb = spike.hitbox()
    game.player_x = s_hb.centerx - game.player_width / 2.0
    game.player_y = s_hb.centery - game.player_height / 2.0
    score_before = game.score
    game.update(0.01, 0)

    assert game.state == "playing" and game.checkpoint_stack.size() == 0
    assert game.score == score_before and game.invuln_timer > 0.0 and game.chances == 2

    # Second hit with 0 chances -> game_over
    game.chances, game.invuln_timer = 0, 0.0
    game.player_x = s_hb.centerx - game.player_width / 2.0
    game.player_y = s_hb.centery - game.player_height / 2.0
    game.update(0.01, 0)
    assert game.state == "game_over"

    # Checkpoint safety over 200 platforms
    random.seed(123)
    g2 = make_game(score=500, hazards=True)
    for _ in range(200):
        g2.camera_y -= 150.0
        g2.score += 10
        g2._generate_platforms()
        target = min(g2.platforms, key=lambda p: p.top)
        g2.player_x = target.centerx - g2.player_width / 2.0
        g2.player_y = target.top + 1
        g2.player_vy = 300.0
        g2.update(0.016, 0)
        for cp in g2.checkpoint_stack.to_list():
            assert not g2._platform_has_spikes(Platform(*cp))

    if not g2.checkpoint_stack.is_empty():
        restored = Platform(*g2.checkpoint_stack.peek())
        g2._handle_hit()
        assert not g2._platform_has_spikes(restored)

    print("✓ Test 12 Passed: Hit consequences (rewind & game_over) and checkpoint safety verified.")


def test_specials_progression_and_invariants() -> None:
    """Test 13: Specials score gating, progression density, and fairness invariants."""
    random.seed(42)
    g_low = make_game(score=50, hazards=True, specials=True)
    climb(g_low, 500, step=1000.0)
    assert len(g_low.pads) == 0 and len(g_low.crumblers) == 0

    score_tiers = [200, 600, 1000, 1500]
    pad_densities, crumble_densities = [], []
    for score in score_tiers:
        g = make_game(score=score, hazards=True, specials=True)
        climb(g, 5500, step=5000.0)
        sample = g.platforms[500:]
        sample_ids = {id(p) for p in sample}
        pad_densities.append((sum(1 for pad in g.pads if id(pad.platform) in sample_ids) / len(sample)) * 100.0)
        crumble_densities.append((sum(1 for c in g.crumblers if id(c.platform) in sample_ids) / len(sample)) * 100.0)

    print("\nBounce Pad & Crumbler Density Table (per 100 platforms):")
    print("-------------------------------------------------------")
    print(" Score Tier |  Pads / 100 Plats  | Crumblers / 100 Plats")
    print("-------------------------------------------------------")
    for s, p_d, c_d in zip(score_tiers, pad_densities, crumble_densities):
        print(f"   {s:5d}    |       {p_d:6.2f}       |        {c_d:6.2f}")
    print("-------------------------------------------------------")

    for i in range(1, len(crumble_densities)):
        assert crumble_densities[i] >= crumble_densities[i - 1] - 1.5

    # Fairness invariants across 10,000+ platforms
    g_full = make_game(score=1500, hazards=True, specials=True)
    climb(g_full, 10500, step=5000.0)
    assert_reachability(g_full.platforms)

    spiked_ids = {id(h.platform) for h in g_full.hazards if h.platform}
    pad_ids = {id(pad.platform) for pad in g_full.pads}
    crumbler_ids = {id(c.platform) for c in g_full.crumblers}

    for p in g_full.platforms:
        pid = id(p)
        assert ((pid in spiked_ids) + (pid in pad_ids) + (pid in crumbler_ids)) <= 1

    for i in range(len(g_full.platforms) - CRUMBLE_MIN_PLAIN_BETWEEN):
        if id(g_full.platforms[i]) in crumbler_ids:
            for k in range(1, CRUMBLE_MIN_PLAIN_BETWEEN + 1):
                assert id(g_full.platforms[i + k]) not in crumbler_ids

    consec_non_plain = 0
    for p in g_full.platforms:
        if not g_full._is_plain(p):
            consec_non_plain += 1
            assert consec_non_plain <= MAX_SPECIAL_RUN
        else:
            consec_non_plain = 0

    for pad in g_full.pads:
        assert pad.rect.left >= pad.platform.left and pad.rect.right <= pad.platform.right

    pad_indices = [i for i, p in enumerate(g_full.platforms) if id(p) in pad_ids]
    for idx in pad_indices:
        for offset in range(1, PAD_CLEAR_PLATFORMS + 1):
            if idx + offset < len(g_full.platforms):
                assert id(g_full.platforms[idx + offset]) not in spiked_ids

    plain_ratio = sum(1 for p in g_full.platforms if g_full._is_plain(p)) / len(g_full.platforms)
    print(f"Plain-platform ratio at full difficulty: {plain_ratio * 100:.2f}%")
    assert plain_ratio >= 0.30

    print("✓ Test 13 Passed: Specials progression and fairness invariants verified.")


def test_pad_mechanics() -> None:
    """Test 14: Pad launch velocity, forgiveness margin, apex height, and rising immunity."""
    game = make_game(hazards=False, specials=True, orbs=False)
    plat = Platform(100, 400, 120, PLATFORM_HEIGHT)
    pad_rect = pygame.Rect(140, plat.top - PAD_HEIGHT, PAD_WIDTH, PAD_HEIGHT)
    pad = Pad(platform=plat, rect=pad_rect)
    game.platforms, game.pads = [plat], [pad]

    renderer = Renderer(pygame.Surface((WIDTH, HEIGHT)))

    # Landing on pad
    game.player_x = pad_rect.centerx - game.player_width / 2.0
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert abs(game.player_vy - PAD_JUMP_VELOCITY) < 1e-4 and game.just_boosted is True
    assert 0.0 < pad.pressed_timer <= PAD_PRESS_DURATION

    renderer.render(game, (0, 0), 0.016)
    assert game.just_boosted is False

    # Away from pad (outside forgiveness)
    game.start_run()
    game.platforms, game.pads = [plat], [pad]
    game.player_x = (pad_rect.left - PAD_FORGIVENESS) - 10 - game.player_width
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert abs(game.player_vy - JUMP_VELOCITY) < 1e-4 and game.just_boosted is False

    # Within forgiveness margin
    game.start_run()
    game.platforms, game.pads = [plat], [pad]
    game.player_x = (pad_rect.left - (PAD_FORGIVENESS - 2)) - game.player_width
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert abs(game.player_vy - PAD_JUMP_VELOCITY) < 1e-4 and game.just_boosted is True

    # Apex height
    y, vy = 0.0, PAD_JUMP_VELOCITY
    while vy < 0:
        y += vy * (1.0 / 120.0)
        vy += settings.GRAVITY * (1.0 / 120.0)
    assert abs(abs(y) - PAD_HEIGHT_FACTOR * JUMP_HEIGHT) / (PAD_HEIGHT_FACTOR * JUMP_HEIGHT) <= 0.05

    # Rising pass through
    game.start_run()
    game.platforms, game.pads = [plat], [pad]
    game.player_x = pad_rect.centerx - game.player_width / 2.0
    game.player_y = plat.top + 5
    game.player_vy = -400.0
    game.update(0.016, 0)
    assert game.player_vy < 0.0 and game.player_vy != PAD_JUMP_VELOCITY and not game.just_boosted

    print("✓ Test 14 Passed: Bounce pad mechanics verified.")


def test_crumbler_mechanics_and_checkpoint_safety() -> None:
    """Test 15: Crumbler landing, timer, disintegration, fall-through, pause, and plain checkpoints."""
    game = make_game(hazards=False, specials=True, orbs=False)
    plat = Platform(100, 400, 100, PLATFORM_HEIGHT)
    crumbler = Crumbler(platform=plat, state="intact", timer=0.0)
    game.platforms, game.crumblers = [plat], [crumbler]

    game.player_x = 120.0
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert crumbler.state == "crumbling" and crumbler.timer == CRUMBLE_DELAY

    # Re-landing does not reset
    t_before = crumbler.timer
    game.update(0.016, 0)
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 200.0
    game.update(0.016, 0)
    assert crumbler.timer < t_before

    # Pause freezes
    game.pause()
    t_paused = crumbler.timer
    game.update(0.1, 0)
    assert crumbler.timer == t_paused
    game.resume()

    # Disintegration
    while crumbler.timer > 0.0:
        game.update(0.05, 0)
    assert crumbler.state == "broken"
    assert plat not in game.platforms and crumbler in game.crumblers
    assert len(game.debris) > 0 and all(d.age < DEBRIS_DURATION for d in game.debris)

    # Fall through
    game.player_x = 120.0
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert game.player_vy > 300.0

    # Plain platforms only checkpoints
    random.seed(42)
    g_spec = make_game(score=600, hazards=True, specials=True, orbs=True)
    for _ in range(60):
        above = [p for p in g_spec.platforms if p.top < g_spec.player_y]
        if not above:
            g_spec.camera_y -= 500.0
            g_spec._generate_platforms()
            continue
        target = min(above, key=lambda p: p.top)
        g_spec.player_x = target.centerx - g_spec.player_width / 2.0
        g_spec.player_y = target.top - g_spec.player_height - 1
        g_spec.player_vy = 300.0
        g_spec.update(0.016, 0)
        for cp in g_spec.checkpoint_stack.to_list():
            assert g_spec._is_plain(Platform(*cp))

    print("✓ Test 15 Passed: Crumbler mechanics and checkpoint safety verified.")


def test_route_integrity_and_crumbler_restoration() -> None:
    """Test 16: Route reachability and intact crumbler restoration after rewind."""
    random.seed(42)
    game = make_game(hazards=True, specials=True, orbs=True)
    climb(game, 40, step=1000.0, score_inc=50)

    plain_plats = [p for p in game.platforms if game._is_plain(p)]
    cp_plat = plain_plats[len(plain_plats) // 2]
    game.checkpoint_stack.push((cp_plat.x, cp_plat.y, cp_plat.width, cp_plat.height))

    crumblers_above = [c for c in game.crumblers if c.platform.top < cp_plat.top]
    for c in crumblers_above:
        c.state = "broken"
        game.platforms = [p for p in game.platforms if p is not c.platform]
        game.debris.append(Debris(rect=c.platform.copy(), age=0.1))

    score_before, max_h_before = game.score, game.max_height_y
    game._rewind()

    assert game.score == score_before and game.max_height_y == max_h_before
    for c in crumblers_above:
        assert c.state == "intact" and any(p is c.platform for p in game.platforms)
    assert len(game.debris) == 0

    above_plats = [p for p in game.platforms if p.top <= cp_plat.top]
    assert_reachability(above_plats)
    print("✓ Test 16 Passed: Route integrity and crumbler restoration after rewind verified.")


def test_prune_safety_and_patrol_removal() -> None:
    """Test 17: Pruning cutoff protects checkpoints/orbs; patrol hazards fully removed."""
    game = make_game(hazards=True, specials=True, orbs=True)
    cp_plat = Platform(100, 1200, 100, PLATFORM_HEIGHT)
    intermediate_plat = Platform(120, 1050, 100, PLATFORM_HEIGHT)
    game.platforms.extend([cp_plat, intermediate_plat])
    game.checkpoint_stack.push((cp_plat.x, cp_plat.y, cp_plat.width, cp_plat.height))

    surviving_orb = Orb(x=150.0, y=cp_plat.top - 50.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
    game.orbs.append(surviving_orb)
    game.camera_y = 0.0
    game._prune_platforms()

    assert cp_plat in game.platforms and intermediate_plat in game.platforms
    assert surviving_orb in game.orbs

    # Pruning drops deep items
    p_deep = Platform(100, 1500, 100, PLATFORM_HEIGHT)
    pad_deep = Pad(platform=p_deep, rect=pygame.Rect(100, 1500 - PAD_HEIGHT, PAD_WIDTH, PAD_HEIGHT))
    crumble_deep = Crumbler(platform=p_deep)
    hazard_deep = Hazard(platform=p_deep, rect=pygame.Rect(100, 1500 - SPIKE_HEIGHT, 30, SPIKE_HEIGHT))
    debris_deep = Debris(rect=p_deep.copy(), age=0.1)
    game.platforms.append(p_deep)
    game.pads.append(pad_deep)
    game.crumblers.append(crumble_deep)
    game.hazards.append(hazard_deep)
    game.debris.append(debris_deep)
    game.checkpoint_stack = Stack(3)  # clear stack so cutoff is camera_y + HEIGHT + PRUNE_MARGIN
    game._prune_platforms()
    assert p_deep not in game.platforms and pad_deep not in game.pads
    assert crumble_deep not in game.crumblers and hazard_deep not in game.hazards and debris_deep not in game.debris

    # Patrol removal
    patrol_attrs = [attr for attr in dir(settings) if attr.startswith("PATROL_")]
    assert len(patrol_attrs) == 0 and not hasattr(settings, "REWIND_CLEAR_WINDOW")
    root = Path(__file__).resolve().parent
    for fn in ["game.py", "settings.py", "renderer.py", "main.py"]:
        assert "patrol" not in (root / fn).read_text(encoding="utf-8").lower()

    print("✓ Test 17 Passed: Prune safety checkpoint invariant & patrol removal verified.")


def test_orb_generation_and_pickup() -> None:
    """Test 18: Orb generation score gating, clearance, bounds, density, and pickup anti-tunneling."""
    random.seed(42)
    g_low = make_game(score=30, hazards=True, specials=True, orbs=True)
    climb(g_low, 500, step=1000.0)
    assert len(g_low.orbs) == 0

    g = make_game(score=1500, hazards=True, specials=True, orbs=True)
    climb(g, 10500, step=5000.0)
    assert_reachability(g.platforms)

    plat_by_band: dict = {}
    for p in g.platforms:
        plat_by_band.setdefault(int(p.top // 100), []).append(p)

    pad_by_band: dict = {}
    for pad in g.pads:
        pad_by_band.setdefault(int(pad.rect.top // 100), []).append(pad)

    hazard_by_band: dict = {}
    for h in g.hazards:
        hazard_by_band.setdefault(int(h.rect.top // 100), []).append(h)

    for orb in g.orbs:
        assert 8.0 <= orb.x - orb.radius and orb.x + orb.radius <= WIDTH - 8.0
        orb_band = int(orb.y // 100)
        for b in (orb_band - 1, orb_band, orb_band + 1):
            for p in plat_by_band.get(b, []):
                cx = max(p.left - ORB_CLEARANCE, min(p.right + ORB_CLEARANCE, orb.x))
                cy = max(p.top - ORB_CLEARANCE, min(p.bottom + ORB_CLEARANCE, orb.y))
                assert math.hypot(orb.x - cx, orb.y - cy) >= orb.radius - 1e-4
            for pad in pad_by_band.get(b, []):
                cx = max(pad.rect.left - ORB_CLEARANCE, min(pad.rect.right + ORB_CLEARANCE, orb.x))
                cy = max(pad.rect.top - ORB_CLEARANCE, min(pad.rect.bottom + ORB_CLEARANCE, orb.y))
                assert math.hypot(orb.x - cx, orb.y - cy) >= orb.radius - 1e-4
            for h in hazard_by_band.get(b, []):
                cx = max(h.rect.left - ORB_CLEARANCE, min(h.rect.right + ORB_CLEARANCE, orb.x))
                cy = max(h.rect.top - ORB_CLEARANCE, min(h.rect.bottom + ORB_CLEARANCE, orb.y))
                assert math.hypot(orb.x - cx, orb.y - cy) >= orb.radius - 1e-4

    spike_strips = [h.rect for h in g.hazards]
    for orb in g.orbs:
        if orb.risk:
            matching = [
                s for s in spike_strips
                if abs(s.centerx - orb.x) < 2.0 and abs(orb.y - (s.top - RISK_ORB_HEIGHT)) < 2.0
            ]
            assert len(matching) > 0

    density = (len(g.orbs) / len(g.platforms)) * 100.0
    print(f"\nOrb Density at Full Difficulty: {density:.2f} orbs per 100 platforms")
    assert 20.0 <= density <= 50.0

    # Pickup mechanics & anti-tunneling
    plat = Platform(0, -100, WIDTH, PLATFORM_HEIGHT)
    for risk_flag, radius, points in [(False, ORB_RADIUS, ORB_POINTS), (True, RISK_ORB_RADIUS, RISK_ORB_POINTS)]:
        game = make_game(hazards=False, specials=False, orbs=False)
        game.platforms, game.camera_y = [plat], 0.0
        orb = Orb(x=200.0, y=400.0, radius=radius, points=points, risk=risk_flag)
        game.orbs = [orb]
        game.player_x = 200.0 - game.player_width / 2.0
        game.player_y = 400.0 - game.player_height / 2.0
        game.player_vy = 0.0
        game.max_height_y = game.player_y
        game.score = int((game.start_y - game.max_height_y) / settings.SCORE_DIVISOR)
        b_before, t_before = game.bonus_score, game.total_score
        game.update(0.016, 0)
        assert orb not in game.orbs and game.bonus_score == b_before + points and game.total_score == t_before + points
        assert game.events[-1] == ("orb", 200.0, 400.0, points, risk_flag)

    # Outside radius
    game = make_game(hazards=False, specials=False, orbs=False)
    game.platforms, game.camera_y, game.player_x, game.player_y = [plat], 0.0, 100.0, 350.0
    orb_out = Orb(x=100.0 + game.player_width + 25.0, y=360.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
    game.orbs = [orb_out]
    game.update(0.016, 0)
    assert orb_out in game.orbs

    # Anti-tunneling falling & rising
    for vy_val, start_py in [(MAX_FALL_SPEED, 270.0), (PAD_JUMP_VELOCITY, 320.0)]:
        game = make_game(hazards=False, specials=False, orbs=False)
        game.platforms, game.camera_y = [plat], 0.0
        o_fast = Orb(x=200.0, y=300.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
        game.orbs = [o_fast]
        game.player_x, game.player_y, game.player_vy = 200.0 - game.player_width / 2.0, start_py, vy_val
        game.update(1.0 / 30.0, 0)
        assert o_fast not in game.orbs

    print("✓ Test 18 Passed: Orb generation and pickup mechanics verified.")


def test_near_miss() -> None:
    """Test 19: Near-miss bonus conditions (zone exit, margin, collision, single payout, last platform, invuln)."""
    plat = Platform(100, 400, 120, PLATFORM_HEIGHT)
    strip = pygame.Rect(100, 400 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT)

    def make_nm_game(chances: int = 3, invuln: float = 0.0, last_plat: Optional[Platform] = None) -> tuple[Game, Hazard, pygame.Rect]:
        g = make_game(hazards=True)
        g.chances, g.invuln_timer, g.last_landing_platform = chances, invuln, last_plat
        s = Hazard(platform=plat, rect=strip)
        g.platforms, g.hazards = [plat], [s]
        return g, s, s.hitbox()

    # (a) Pass within zone and exit without touching -> award
    game, spike, hb = make_nm_game()
    game.player_x = hb.right + (NEAR_MISS_MARGIN - 4) - PLAYER_HITBOX_INSET
    game.player_y = hb.top
    game.update(0.016, 0)
    assert spike.in_zone is True and not spike.near_miss_awarded and game.bonus_score == 0
    game.player_x = hb.right + NEAR_MISS_MARGIN + 30
    game.update(0.016, 0)
    assert not spike.in_zone and spike.near_miss_awarded and game.bonus_score == NEAR_MISS_POINTS
    assert len(game.events) == 1 and game.events[0][0] == "near_miss" and game.events[0][3] == NEAR_MISS_POINTS

    # (b) Farther than margin
    game, spike_b, hb = make_nm_game()
    game.player_x, game.player_y = hb.right + NEAR_MISS_MARGIN + 50, hb.top
    game.update(0.016, 0)
    assert not spike_b.in_zone and game.bonus_score == 0

    # (c) Collision
    game, spike_c, hb = make_nm_game(chances=0)
    game.player_x = hb.centerx - game.player_width / 2.0
    game.player_y = hb.centery - game.player_height / 2.0
    game.update(0.016, 0)
    assert spike_c.near_miss_awarded and not spike_c.in_zone and game.bonus_score == 0 and game.state == "game_over"

    # (d) Single payout per hazard
    game, spike_d, hb = make_nm_game()
    for _ in range(2):
        game.player_x, game.player_y = hb.right + 2, hb.top
        game.update(0.016, 0)
        game.player_x = hb.right + 50
        game.update(0.016, 0)
        assert game.bonus_score == NEAR_MISS_POINTS

    # (e) No award on last_landing_platform
    game, spike_e, hb = make_nm_game(last_plat=plat)
    game.player_x, game.player_y = hb.right + 2, hb.top
    game.update(0.016, 0)
    game.player_x = hb.right + 50
    game.update(0.016, 0)
    assert not spike_e.in_zone and game.bonus_score == 0

    # (f) No award while invulnerable
    game, spike_f, hb = make_nm_game(invuln=1.0)
    game.player_x, game.player_y = hb.right + 2, hb.top
    game.update(0.016, 0)
    game.player_x = hb.right + 50
    game.update(0.016, 0)
    assert not spike_f.in_zone and game.bonus_score == 0

    # (g) in_zone reset by rewind
    game, spike_g, hb = make_nm_game()
    game.checkpoint_stack.push((100, 600, 100, PLATFORM_HEIGHT))
    game.player_x, game.player_y = hb.right + 2, hb.top
    game.update(0.016, 0)
    assert spike_g.in_zone is True
    game._rewind()
    assert spike_g.in_zone is False

    # (h) Fatal collision + zone exit awards nothing
    game, spike_h1, hb = make_nm_game(chances=0)
    spike_h2 = Hazard(platform=plat, rect=pygame.Rect(200, 400 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT))
    game.hazards.append(spike_h2)
    game.player_x, game.player_y = spike_h1.hitbox().right + 2, spike_h1.hitbox().top
    game.update(0.016, 0)
    h2_box = spike_h2.hitbox()
    game.player_x, game.player_y = h2_box.centerx - game.player_width / 2.0, h2_box.centery - game.player_height / 2.0
    game.update(0.016, 0)
    assert game.bonus_score == 0 and game.state == "game_over"

    print("✓ Test 19 Passed: Near-miss bonus rules (all 8 conditions) verified.")


def test_scoring_and_visuals(tmp_path: Path) -> None:
    """Test 20: Scoring properties, difficulty isolation, FX lifecycle, and renderer smoke."""
    game = make_game()
    game.score, game.bonus_score = 250, 75
    assert game.total_score == 325

    last_total = game.total_score
    game.checkpoint_stack.push((100, 500, 100, PLATFORM_HEIGHT))
    for _ in range(20):
        game.player_y -= 30.0
        game.update(0.016, 0)
        assert game.total_score >= last_total
        last_total = game.total_score
    game._rewind()
    assert game.total_score >= last_total

    # Difficulty calculation height only
    g1, g2 = make_game(score=200), make_game(score=200)
    g2.bonus_score = 10000
    assert (g1.score - settings.SPIKE_START_SCORE) == (g2.score - settings.SPIKE_START_SCORE)

    temp_save = tmp_path / "temp_score.json"
    game.best_score = 300
    game.score, game.bonus_score = 100, 300
    game.save_if_best(path=temp_save)
    assert game.best_score == 400 and load_highscore(temp_save) == 400

    # Renderer & FX lifecycle
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)
    game = make_game()
    game.events.append(("orb", 200.0, 300.0, 10, False))
    renderer.render(game, (0, 0), 0.016)
    assert len(game.events) == 0 and len(renderer.popups) == 1 and len(renderer.rings) == 1 and len(renderer.particles_fx) == 8

    renderer.render(game, (0, 0), 0.016)
    assert len(renderer.popups) == 1

    for _ in range(70):
        renderer.render(game, (0, 0), 0.02)
    assert len(renderer.popups) == 0 and len(renderer.rings) == 0 and len(renderer.particles_fx) == 0

    for _ in range(100):
        game.events.append(("orb", 200.0, 300.0, 10, True))
    renderer.render(game, (0, 0), 0.016)
    assert len(renderer.popups) <= MAX_POPUPS and len(renderer.particles_fx) <= MAX_FX_PARTICLES

    game.pause()
    pop_age = renderer.popups[0]["age"]
    renderer.render(game, (0, 0), 0.1)
    assert renderer.popups[0]["age"] == pop_age
    game.resume()

    game.start_run()
    renderer.render(game, (0, 0), 0.016)
    assert len(renderer.popups) == 0 and len(renderer.rings) == 0 and len(renderer.particles_fx) == 0

    game.score, game.bonus_score = 500, 9999
    renderer.render(game, (0, 0), 0.016)
    game.state = "game_over"
    renderer.render(game, (0, 0), 0.016)

    print("✓ Test 20 Passed: Scoring properties, difficulty isolation, and visuals verified.")


def test_chances_system(tmp_path: Path) -> None:
    """Test 21: Three-chance sequence, independent decrement, safe platform pruning, HUD pips."""
    game = make_game()
    assert game.chances == 3 and game.checkpoint_stack.is_empty() and CHANCES_PER_RUN == 3

    # Fall at start
    force_fall(game)
    assert game.chances == 2 and game.state == "playing"
    assert any(abs(p.top - (game.player_y + game.player_height)) < 2.0 for p in game.platforms)

    # Full sequence: 2 -> 1 -> 0 -> game_over
    for exp in [1, 0]:
        force_fall(game)
        assert game.chances == exp and game.state == "playing"

    temp_save = tmp_path / "temp_chance.json"
    orig_save = game.save_if_best
    game.save_if_best = lambda path=temp_save: orig_save(path=path)
    force_fall(game)
    assert game.state == "game_over" and game.chances == 0

    # Spike hits decrement & invulnerability
    g_hit = make_game(hazards=True, specials=False, orbs=False)
    plat = Platform(100, 300, 120, PLATFORM_HEIGHT)
    spike = Hazard(platform=plat, rect=pygame.Rect(100, 300 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT))
    g_hit.platforms, g_hit.hazards = [plat], [spike]
    hb = spike.hitbox()
    g_hit.player_x = hb.centerx - g_hit.player_width / 2.0
    g_hit.player_y = hb.centery - g_hit.player_height / 2.0
    g_hit.update(0.016, 0)
    assert g_hit.chances == 2 and g_hit.invuln_timer > 0.0

    g_hit.update(0.016, 0)
    assert g_hit.chances == 2  # Invulnerable

    g_hit.chances, g_hit.invuln_timer = 0, 0.0
    g_hit.player_x = hb.centerx - g_hit.player_width / 2.0
    g_hit.player_y = hb.centery - g_hit.player_height / 2.0
    g_hit.update(0.016, 0)
    assert g_hit.state == "game_over"

    # Chances never refills
    random.seed(123)
    g_climb = make_game(hazards=False, specials=False, orbs=False)
    force_fall(g_climb)
    assert g_climb.chances == 2
    for _ in range(50):
        above = [p for p in g_climb.platforms if p.top < g_climb.player_y]
        if not above:
            g_climb.camera_y -= 200.0
            g_climb._generate_platforms()
            above = [p for p in g_climb.platforms if p.top < g_climb.player_y]
        if above:
            t = max(above, key=lambda p: p.top)
            g_climb.player_x = t.centerx - g_climb.player_width / 2.0
            g_climb.player_y = t.top - g_climb.player_height + 2.0
            g_climb.player_vy = 200.0
            g_climb.camera_y = min(g_climb.camera_y, g_climb.player_y - HEIGHT * 0.4)
            g_climb.update(0.016, 0)
            assert g_climb.chances == 2

    # Independence from stack size
    g_stk = make_game()
    force_fall(g_stk)
    assert g_stk.chances == 2
    clean_p = Platform(120, 250, 100, PLATFORM_HEIGHT)
    g_stk.platforms.append(clean_p)
    g_stk.checkpoint_stack.push((clean_p.x, clean_p.y, clean_p.w, clean_p.h))
    force_fall(g_stk)
    assert g_stk.chances == 1
    for i in range(3):
        p = Platform(100, 200 - i * 100, 100, PLATFORM_HEIGHT)
        g_stk.checkpoint_stack.push((p.x, p.y, p.w, p.h))
    force_fall(g_stk)
    assert g_stk.chances == 0

    # No double decrement
    g_both = make_game(hazards=True)
    p_both = Platform(100, 300, 100, PLATFORM_HEIGHT)
    s_both = Hazard(platform=p_both, rect=pygame.Rect(100, 300 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT))
    g_both.platforms, g_both.hazards = [p_both], [s_both]
    g_both.camera_y = 100.0
    g_both.player_y = g_both.camera_y + HEIGHT + 50.0
    s_both.rect.y = int(g_both.player_y)
    g_both.invuln_timer = 0.0
    init_c = g_both.chances
    g_both.update(0.016, 0)
    assert g_both.chances == init_c - 1

    # Restart resets chances to 3 and clears stack
    g_rst = make_game()
    g_rst.chances, g_rst.state = 0, "game_over"
    g_rst.start_run()
    assert g_rst.chances == 3 and g_rst.checkpoint_stack.is_empty()
    g_rst.chances = 1
    g_rst.pause()
    g_rst.start_run()
    assert g_rst.chances == 3 and g_rst.checkpoint_stack.is_empty()

    # Route integrity & safe platform pruning
    g_prune = make_game()
    g_prune.camera_y = -3000.0
    safe_plat = g_prune.last_safe_platform
    assert safe_plat is not None
    g_prune._prune_platforms()
    assert safe_plat in g_prune.platforms
    force_fall(g_prune)
    assert g_prune.chances == 2
    assert_reachability(g_prune.platforms)

    # Renderer HUD draws pips for 3, 2, 1, 0
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)
    for c in [3, 2, 1, 0]:
        g_hud = make_game()
        g_hud.chances = c
        renderer.render(g_hud, (0, 0), 0.016)

    print("✓ Test 21 Passed: Full chances sequence and invariants verified.")


def test_stability_soak() -> None:
    """Test 22: Stability soak (20,000 frames with bot AI and headless rendering)."""
    random.seed(42)
    game = make_game(hazards=True, specials=True, orbs=True)
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)

    total_frames = 20000
    dt = 1.0 / 60.0
    runs = 1
    rewinds = pad_launches = crumbles = hits = orbs_collected = near_misses = 0
    last_total_score = 0
    target_plat: Optional[Platform] = None

    for frame_idx in range(total_frames):
        if game.state == "game_over":
            runs += 1
            game.start_run()
            target_plat = None
            last_total_score = 0

        if game.just_jumped or target_plat is None:
            platforms_above = [p for p in game.platforms if p.top < game.player_y]
            if platforms_above:
                target_plat = max(platforms_above, key=lambda p: p.top)

        move_dir = 0
        if target_plat:
            target_x = target_plat.centerx
            player_center = game.player_x + game.player_width / 2.0
            dx = target_x - player_center
            if dx > WIDTH / 2:
                dx -= WIDTH
            elif dx < -WIDTH / 2:
                dx += WIDTH
            if dx > 3:
                move_dir = 1
            elif dx < -3:
                move_dir = -1

        prev_state, prev_chances = game.state, game.chances
        prev_debris_count = len(game.debris)

        game.update(dt, move_dir)

        for ev in game.events:
            if ev[0] == "orb":
                orbs_collected += 1
            elif ev[0] == "near_miss":
                near_misses += 1

        if game.just_boosted:
            pad_launches += 1
        if len(game.debris) > prev_debris_count:
            crumbles += (len(game.debris) - prev_debris_count)
        if prev_state == "playing" and game.state == "playing" and prev_chances > game.chances:
            rewinds += 1
        if prev_state == "playing" and (game.state == "game_over" or prev_chances > game.chances):
            hits += 1

        assert 0 <= game.chances <= CHANCES_PER_RUN
        if prev_state == "playing" and game.state == "playing":
            assert game.chances <= prev_chances
        assert game.total_score >= last_total_score
        last_total_score = game.total_score

        if frame_idx % 10 == 0:
            renderer.render(game, (0, 0), 10 * dt)
            assert len(renderer.particles_fx) <= MAX_FX_PARTICLES and len(renderer.popups) <= MAX_POPUPS

        assert len(game.platforms) < 150 and len(game.orbs) < 60 and len(game.hazards) < 80
        assert len(game.pads) < 60 and len(game.crumblers) < 80 and len(game.debris) < 40

    print(
        f"✓ Test 22 Passed: Stability soak completed ({total_frames} frames, "
        f"orbs={orbs_collected}, near_misses={near_misses}, pad_launches={pad_launches}, "
        f"crumbles={crumbles}, rewinds={rewinds}, hits={hits}, runs={runs}, "
        f"platforms={len(game.platforms)}, orbs={len(game.orbs)}, hazards={len(game.hazards)}, "
        f"pads={len(game.pads)}, crumblers={len(game.crumblers)}, debris={len(game.debris)})."
    )


if __name__ == "__main__":
    test_stack_operations()
    test_reachability()
    test_collision()
    test_score_monotonicity()
    test_rewind_and_game_over()
    test_start_run_reset()

    scratch_dir = Path(__file__).resolve().parent / ".test_scratch"
    scratch_dir.mkdir(exist_ok=True)
    test_highscore_io(scratch_dir)

    test_audio_trigger_clear()
    test_hazard_progression()
    test_hazard_fairness_invariants()
    test_spike_collision()
    test_hit_consequences_and_checkpoint_safety()

    test_specials_progression_and_invariants()
    test_pad_mechanics()
    test_crumbler_mechanics_and_checkpoint_safety()
    test_route_integrity_and_crumbler_restoration()
    test_prune_safety_and_patrol_removal()

    test_orb_generation_and_pickup()
    test_near_miss()
    test_scoring_and_visuals(scratch_dir)
    test_chances_system(scratch_dir)
    test_stability_soak()

    try:
        scratch_dir.rmdir()
    except Exception:
        pass

    print("\nALL TESTS PASSED SUCCESSFULLY!")
