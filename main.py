"""Main entry point and game loop for One More Jump.

Initializes Pygame, handles keyboard and mouse input events, advances
simulation state, and renders the visual presentation at 60 FPS.
"""

import sys
import pygame

from game import Game
from renderer import (
    Renderer,
    get_game_over_menu_button_rect,
    get_game_over_restart_button_rect,
    get_hud_pause_button_rect,
    get_menu_play_button_rect,
    get_pause_menu_button_rect,
    get_pause_restart_button_rect,
    get_pause_resume_button_rect,
)
from settings import FPS, HEIGHT, TITLE, WIDTH


def main() -> None:
    """Initialize system resources and execute the core application loop."""
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(TITLE)
    clock = pygame.time.Clock()

    game = Game()
    renderer = Renderer(screen)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        mouse_pos = pygame.mouse.get_pos()

        # Process input events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.save_if_best()
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if game.state == "playing":
                        game.pause()
                    elif game.state == "paused":
                        game.resume()
                    elif game.state == "menu":
                        game.save_if_best()
                        running = False
                    elif game.state == "game_over":
                        game.state = "menu"

                elif event.key == pygame.K_p:
                    if game.state in ("playing", "paused"):
                        game.toggle_pause()

                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if game.state == "menu":
                        game.start_run()
                    elif game.state == "game_over":
                        game.start_run()
                    elif game.state == "paused":
                        game.resume()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Left-click mouse button handling across all game states
                if game.state == "menu":
                    if get_menu_play_button_rect().collidepoint(mouse_pos):
                        game.start_run()

                elif game.state == "playing":
                    if get_hud_pause_button_rect().collidepoint(mouse_pos):
                        game.pause()

                elif game.state == "paused":
                    if get_pause_resume_button_rect().collidepoint(mouse_pos):
                        game.resume()
                    elif get_pause_restart_button_rect().collidepoint(mouse_pos):
                        game.start_run()
                    elif get_pause_menu_button_rect().collidepoint(mouse_pos):
                        game.state = "menu"

                elif game.state == "game_over":
                    if get_game_over_restart_button_rect().collidepoint(mouse_pos):
                        game.start_run()
                    elif get_game_over_menu_button_rect().collidepoint(mouse_pos):
                        game.state = "menu"

        # Continuous steering input from held keys
        move_dir = 0
        if game.state == "playing":
            keys = pygame.key.get_pressed()
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                move_dir -= 1
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                move_dir += 1

            game.update(dt, move_dir)

        # Draw frame
        renderer.render(game, mouse_pos, dt)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
