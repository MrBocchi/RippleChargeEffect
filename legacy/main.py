import sys
import os
import json
import time
import ctypes
import ctypes.wintypes
import numpy as np
import psutil
import shutil

# Suppress debug logs internally from ModernGL
os.environ['VG_GL_PROFILE'] = 'core' 

import pygame
import pygame.freetype
import moderngl
import mss

# --- Constants & Defaults ---
DEFAULT_CONFIG = {
    "window": {
        "width": 1920,
        "height": 1200,
        "x": "center",
        "y": "center"
    },
    "color": [90, 255, 120],
    "alpha": 0.85,
    "bg_darkness": 0.2,
    "charge_direction": "1"
}

def load_config():
    """ Load or create configuration definition file. """
    cfg_path = os.path.join("config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    return DEFAULT_CONFIG

def main():
    config = load_config()

    # Opt-in for Dpi Awarness mode to avoid auto-scaling stretching by Windows
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
    except Exception:
        pass

    # Stop pygame/SDL from attempting to minimize when losing focus or clicking away
    os.environ["SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS"] = "0"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

    # Only initialize necessary subsystems to bypass mixer/joystick cold start penalties
    pygame.display.init()
    pygame.freetype.init()

    # Determine render resolution
    win_w = config["window"]["width"]
    win_h = config["window"]["height"]

    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    # Prevent Hardware Fullscreen Exclusive Mode which causes black screen flickering
    if win_w >= screen_w and win_h >= screen_h:
        win_w = screen_w
        win_h = screen_h - 1  # Reduce height by 1px to bypass Windows exclusive mode

    win_x = config["window"]["x"]
    win_y = config["window"]["y"]

    if win_x == "center":
        win_x = (screen_w - win_w) // 2
    else:
        win_x = int(win_x)
        
    if win_y == "center":
        win_y = (screen_h - win_h) // 2
    else:
        win_y = int(win_y)

    # Pre-configure pygame container window properties
    os.environ['SDL_VIDEO_WINDOW_POS'] = f"{win_x},{win_y}"
    
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    
    # Hidden init via pygame window position allows us to prep the window before it flashes on screen
    os.environ['SDL_VIDEO_WINDOW_POS'] = f"{win_x},{win_y}"
    
    screen = pygame.display.set_mode((win_w, win_h), pygame.OPENGL | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HIDDEN)

    # Windows API calls to shape window visibility
    # For global mouse hooking we'll need ctypes struct definitions if click_exit is enabled
    if sys.platform == "win32":
        hwnd = pygame.display.get_wm_info()["window"]
        
        # Set HWND_TOPMOST without modifying sizes explicitly, and DO NOT invoke SWP_SHOWWINDOW yet.
        # 0x0001=SWP_NOSIZE, 0x0002=SWP_NOMOVE, 0x0010=SWP_NOACTIVATE
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

        # Apply Layered and Click-through Mouse-Pass properties
        ex_style = user32.GetWindowLongW(hwnd, -20)
        
        # Try a safer layering flag: WS_EX_TOOLWINDOW | WS_EX_APPWINDOW
        # 0x00080000 = WS_EX_LAYERED
        # 0x00000020 = WS_EX_TRANSPARENT
        # 0x00000080 = WS_EX_TOOLWINDOW
        user32.SetWindowLongW(hwnd, -20, ex_style | 0x00000080 | 0x00000020 | 0x00080000)
        
        # Make the window perfectly opaque initially to the layering engine, 
        # so OpenGL purely controls the alpha via `rgba` fragments.
        # But wait! A known issue on Windows + PyGame + Layered window is black screen
        # if LWA_ALPHA is used with OpenGL buffer flipping on certain drivers. 
        # We must use LWA_COLORKEY instead or remove LWA_ALPHA and let DWM composite it!
        # Actually in Python/SDL2, OpenGL requires ALPHAFORMAT to blend cleanly:
        # We can bypass SetLayeredWindowAttributes and rely entirely on SDL's transparency if possible,
        # but for true mouse-pass we keep it but with full 255.
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x00000002) 

        # Very Important Flag for real-time visual refraction: WDA_EXCLUDEFROMCAPTURE
        # Completely omits this active window from capture pipelines, allowing MSS to fetch pure desktop pixels behind it dynamically
        try:
            # Note: WDA_EXCLUDEFROMCAPTURE = 0x00000011
            user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
        except Exception as e:
            print("Warning: WDA_EXCLUDEFROMCAPTURE flag binding failed.", e)

    # Setup OpenGL Context
    ctx = moderngl.create_context()

    # Load custom shader
    shader_path = os.path.path.join("shader.glsl") if not os.path.exists("shader.glsl") else "shader.glsl"
    with open(shader_path, "r", encoding="utf-8") as f:
        fragment_shader = f.read()

    prog = ctx.program(
        vertex_shader="""
            #version 330 core
            in vec2 in_vert;
            out vec2 uvs;
            void main() {
                gl_Position = vec4(in_vert, 0.0, 1.0);
                // Translating mathematical coordinates to image coordinates
                uvs = vec2(in_vert.x * 0.5 + 0.5, 0.5 - in_vert.y * 0.5); 
            }
        """,
        fragment_shader=fragment_shader
    )

    vertices = np.array([
        -1.0, -1.0,
         1.0, -1.0,
        -1.0,  1.0,
         1.0,  1.0,
    ], dtype="f4")

    vbo = ctx.buffer(vertices.tobytes())
    vao = ctx.vertex_array(prog, [(vbo, '2f', 'in_vert')])

    # Allocate graphic layers for capturing frame
    tex_bg = ctx.texture((win_w, win_h), 4)
    tex_bg.swizzle = 'BGRA' # MSS yields native BGRA buffers instead of RGBA.
    tex_bg.use(0)
    prog['tex_bg'].value = 0

    # Allocate text font rendering buffer
    tex_text = ctx.texture((800, 800), 4)
    tex_text.use(1)
    prog['tex_text'].value = 1

    # Inject static parameters to shader
    prog['resolution'].value = (win_w, win_h)
    
    color_val = config["color"]
    # Handle Hex color string like "#5AFF78"
    if isinstance(color_val, str) and color_val.startswith("#"):
        hex_color = color_val.lstrip("#")
        color = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
    else:
        color = color_val
        
    prog['overlay_color'].value = (color[0]/255.0, color[1]/255.0, color[2]/255.0)
    prog['alpha'].value = float(config["alpha"])
    # 旧有的 bg_darkness 效果设为 0 (保留变量不报错)
    prog['bg_darkness'].value = float(config["bg_darkness"])
    # 注入新的全屏压暗配置
    prog['bg_darkness_new'].value = float(config["bg_darkness_new"])
    
    ring_cfg = config.get("ring", {})
    prog['ripple_distortion'].value = float(ring_cfg.get("ripple_distortion", 0.08))
    prog['ripple_speed'].value = float(ring_cfg.get("ripple_speed", 1.0))
    prog['ring_scale'].value = float(ring_cfg.get("ring_scale", 1.0))
    prog['inner_radius'].value = float(ring_cfg.get("inner_radius", 0.15))
    prog['outer_radius'].value = float(ring_cfg.get("outer_radius", 0.40))
    
    particle_cfg = config.get("particle", {})
    prog['particle_density'].value = float(particle_cfg.get("particle_density", 60.0))
    prog['particle_speed'].value = float(particle_cfg.get("particle_speed", 0.04))
    prog['particle_enabled'].value = 1.0 if particle_cfg.get("particle_enabled", True) else 0.0
    prog['particle_wave_ratio'].value = float(particle_cfg.get("particle_wave_ratio", 3.0))
    prog['particle_radius_offset'].value = float(particle_cfg.get("particle_radius_offset", 0.02))
    prog['particle_brightness'].value = float(particle_cfg.get("particle_brightness", 3.5))

    line_cfg = config.get("line", {})
    prog['line_thickness'].value = float(line_cfg.get("line_thickness", 0.03))
    prog['l_shape_y_offset'].value = float(line_cfg.get("l_shape_y_offset", 0.35))
    prog['l_shape_curve_radius'].value = float(line_cfg.get("l_shape_curve_radius", 0.12))
    
    prog['global_fade'].value = 0.0 # 初始为 0.0 等待背景完全载入后渐显

    # 读取生命周期设定
    display_duration = float(config.get("display_duration", 5.0))
    auto_exit = bool(config.get("auto_exit", True))
    click_exit = bool(config.get("click_exit", True))
    fade_duration = float(config.get("fade_duration", 1.0))

    dir_val = config.get("charge_direction", 5)
    try:
        dir_mapped = int(dir_val)
    except:
        # Fallback to older string config format if integer wasn't properly used
        dirs_str = {"left": 5, "right": 6, "bottom": 3, "top": 4, "left-l": 1, "right-l": 2}
        dir_mapped = dirs_str.get(str(dir_val).lower(), 5)
    prog['direction'].value = dir_mapped

    # Setup text configuration
    text_cfg = config.get("text", {
        "font_name": "Arial", "size_large": 100, "size_small": 45,
        "color": [255, 255, 255], "decimal_increase_per_sec": 2.0
    })
    
    font_name = text_cfg.get("font_name", "Arial")
    size_large = text_cfg.get("size_large", 100)
    size_small = text_cfg.get("size_small", 45)
    
    text_color_val = text_cfg.get("color", [255, 255, 255])
    if isinstance(text_color_val, str) and text_color_val.startswith("#"):
        hex_color_tc = text_color_val.lstrip("#")
        text_color = tuple([int(hex_color_tc[i:i+2], 16) for i in (0, 2, 4)])
    else:
        text_color = tuple(text_color_val)
        
    text_alpha = text_cfg.get("alpha", 0.9) * 255
    decimal_speed = text_cfg.get("decimal_increase_per_sec", 2.0)
    
    # 动态分辨率倍率计算（以 3456 分辨率为基准 1.0 的参照比）
    # 当 window.height 降低时，不仅圆环本身（依赖于 ring_scale 和 resolution.y 已经同步变小），
    # 它的文字基准也会等比缩小，避免在 1080p 显示器上文字显得过大突出来。
    auto_scale_ratio = win_h / 2160.0
    
    # 获取基础的 text_scale 并应用乘法自动缩放
    base_text_scale = text_cfg.get("text_scale", 1.3)
    prog['text_scale'].value = float(base_text_scale * auto_scale_ratio)

    # 图标大小也同样支持自动缩放以对应不同屏幕
    png_size = int(text_cfg.get("png_size", 80) * auto_scale_ratio)

    font_large = None
    font_small = None
    
    # Fast path: bypass Windows SysFont directory scanning latency for common fonts
    common_fonts = {
        "arial": r"C:/Windows/Fonts/arial.ttf",
        "tahoma": r"C:/Windows/Fonts/tahoma.ttf",
        "segoe ui": r"C:/Windows/Fonts/segoeui.ttf",
        "microsoft yahei": r"C:/Windows/Fonts/msyh.ttc"
    }
    
    fast_path = common_fonts.get(str(font_name).lower())
    if fast_path and os.path.exists(fast_path):
        try:
            font_large = pygame.freetype.Font(fast_path, size_large)
            font_large.strong = True
            font_small = pygame.freetype.Font(fast_path, size_small)
            font_small.strong = True
        except Exception:
            pass

    if not font_large:
        font_large = pygame.freetype.SysFont(font_name, size_large, bold=True)
        if not font_large:
            font_large = pygame.freetype.SysFont(None, size_large, bold=True)
            
        font_small = pygame.freetype.SysFont(font_name, size_small, bold=True)
        if not font_small:
            font_small = pygame.freetype.SysFont(None, size_small, bold=True)

    # Load Image Icon 
    img_path = os.path.join("assets", "lightning.png")
    try:
        lightning_img = pygame.image.load(img_path).convert_alpha()
        lightning_img = pygame.transform.smoothscale(lightning_img, (png_size, png_size))
        # Colorize the white/black image to match text_color if needed
        # Or just keep the native color. We will tint it to text_color:
        lightning_tinted = lightning_img.copy()
        lightning_tinted.fill((*text_color, text_alpha), special_flags=pygame.BLEND_RGBA_MULT)
    except Exception as e:
        print("Fallback: could not load lightning.png", e)
        lightning_tinted = None

# --- 强行夺取前台权限 ---
    try:
        # WS_EX_TOPMOST(0x8) | WS_EX_TOOLWINDOW(0x80) | WS_EX_LAYERED(0x80000) | WS_EX_TRANSPARENT(0x20)
        h_bridge = user32.CreateWindowExW(0x800A8, "Static", "ZBridge", 0x80000000, 0, 0, 1, 1, 0, 0, 0, 0)
        user32.SetLayeredWindowAttributes(h_bridge, 0, 0, 0x02) # 完全透明
        
        # 核心 Hack：模拟按下 Alt 键 (VK_MENU = 0x12) 来绕过 Windows 的 SetForegroundWindow 限制
        user32.keybd_event(0x12, 0, 0, 0) # Alt Down
        user32.ShowWindow(h_bridge, 5)   # SW_SHOW (必须激活以获取真正的 Z-Order 权重)
        user32.SetForegroundWindow(h_bridge)
        user32.keybd_event(0x12, 0, 2, 0) # Alt Up
    except Exception:
        pass
# ----------------------

    sct = mss.mss()
    monitor = {"top": win_y, "left": win_x, "width": win_w, "height": win_h}
    
    # 预先抓取一次背景缓存并填入显存，防止出现应用启动第一眼直接是初始化的黑屏
    try:
        sct_init_img = sct.grab(monitor)
        tex_bg.write(sct_init_img.bgra)
    except Exception as e:
        print("Failed to pre-grab background:", e)

    clock = pygame.time.Clock()
    t0 = time.time()
    last_batt_time = 0
    current_percent = -1
    charge_start_time = 0
    last_text_drawn = ""
    last_bg_cap_time = 0
    
    # 维护生命周期的状态机
    lifecycle_state = "FADE_IN"
    state_start_time = 0.0
    
    # 异步检测全局鼠标点击的基础设置
    mouse_clicked_flags = [False]
    def get_async_keystate():
        if sys.platform == "win32":
            # VK_LBUTTON (0x01) and VK_RBUTTON (0x02) and VK_MBUTTON (0x04)
            return (ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000) != 0 or \
                   (ctypes.windll.user32.GetAsyncKeyState(2) & 0x8000) != 0 or \
                   (ctypes.windll.user32.GetAsyncKeyState(4) & 0x8000) != 0
        return False

    running = True
    while running:
        # If application receives closure event or ESC key
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                # 触发提前退出
                if lifecycle_state != "FADE_OUT":
                    lifecycle_state = "FADE_OUT"
                    state_start_time = t

        t = time.time() - t0
        
        # 持续监控全局鼠标点击，不受鼠标是否在无头窗口内的限制（因为是透明穿透）
        if click_exit and lifecycle_state in ["FADE_IN", "DISPLAY"]:
            if get_async_keystate():
                lifecycle_state = "FADE_OUT"
                # 计算提前开始衰减时的时间轴（如果还在FADE_IN阶段，让它从对应的亮度值反向渐隐）
                current_fade = prog['global_fade'].value
                state_start_time = t - (1.0 - current_fade) * fade_duration
        
        # Check battery metric roughly every 1.5 seconds to save overhead CPU cost
        if time.time() - last_batt_time > 1.5:
            last_batt_time = time.time()
            battery = psutil.sensors_battery()
            new_percent = battery.percent if battery else 100
            if new_percent != current_percent:
                current_percent = new_percent
                charge_start_time = time.time()
                
        # Repaint text dynamically each frame if fake decimals are used (< 100)
        # Even if it's 100%, we draw it once when it updates. So we handle text painting:
        need_paint = False
        display_integer = current_percent
        display_decimal_str = ""
        
        if current_percent < 100:
            need_paint = True
            elapsed_charging = time.time() - charge_start_time
            # Calculate decimal value (0-99), speed is how much it increases per second
            dec_val = int(elapsed_charging * decimal_speed) % 100
            display_decimal_str = f".{dec_val:02d}%"
        else:
            # 100% logic: just draw once when it switches
            # Or draw every frame, 800x800 surface clear and render is very fast
            display_decimal_str = "%"
            need_paint = True

        if need_paint:
            current_text_state = f"{display_integer}_{display_decimal_str}"
            if current_text_state != last_text_drawn:
                last_text_drawn = current_text_state
                text_surf = pygame.Surface((800, 800), pygame.SRCALPHA)
                text_surf.fill((0, 0, 0, 0))
                
                str_large = str(display_integer)
                str_small = display_decimal_str
                
                w_large = font_large.get_rect(str_large).width
                w_small = font_small.get_rect(str_small).width
                
                # Setup horizontal spacing between integer and decimal percentage
                gap_between_text = 8 # add slight spacing
                total_w = w_large + w_small + gap_between_text
                
                # 提取用户通过配置设定的全体文字向上/向下偏移量
                y_offset = text_cfg.get("y_offset", -20)
                
                # Draw line 1: Value + Decimal/Percent
                x_start = (800 - total_w) // 2
                # Vertically center by offsetting slightly up for the thunderbolt, 加上新的偏移量
                y_base = 400 - (size_large // 2) + y_offset
                
                font_large.render_to(text_surf, (x_start, y_base), str_large, fgcolor=(*text_color, text_alpha))
                # Align small text to the baseline
                h_large = font_large.get_rect(str_large).height
                h_small = font_small.get_rect(str_small).height
                y_small = y_base + (h_large - h_small)
                font_small.render_to(text_surf, (x_start + w_large + gap_between_text, y_small), str_small, fgcolor=(*text_color, text_alpha))
            
                # Draw line 2: SVG Icon (or fallback)
                icon_gap_top = 22 # significantly larger than gap_between_text but moderate
                if lightning_tinted:
                    t_w, t_h = lightning_tinted.get_size()
                    t_x = (800 - t_w) // 2
                    t_y = y_base + h_large + icon_gap_top
                    text_surf.blit(lightning_tinted, (t_x, t_y))
                else:
                    thunder_str = "⚡"
                    t_rect = font_small.get_rect(thunder_str)
                    t_x = (800 - t_rect.width) // 2
                    t_y = y_base + h_large + icon_gap_top
                    font_small.render_to(text_surf, (t_x, t_y), thunder_str, fgcolor=(*text_color, text_alpha))
                
                raw_data = pygame.image.tostring(text_surf, "RGBA", False)
                tex_text.write(raw_data)

        # 限频抓取底层屏幕实时动态 (最高 30 FPS)
        if t - last_bg_cap_time > (1.0 / 30.0):
            last_bg_cap_time = t
            try:
                sct_img = sct.grab(monitor)
                tex_bg.write(sct_img.bgra)
            except Exception as e:
                pass # Screen geometry capture bounds error bypass protection

        # 生命期与渐隐状态机逻辑
        global_fade_val = 1.0
        
        if lifecycle_state == "FADE_IN":
            elapsed = t - state_start_time
            if elapsed < fade_duration:
                global_fade_val = elapsed / fade_duration
            else:
                global_fade_val = 1.0
                lifecycle_state = "DISPLAY"
                state_start_time = t
        elif lifecycle_state == "DISPLAY":
            global_fade_val = 1.0
            if auto_exit:
                elapsed = t - state_start_time
                if elapsed >= display_duration:
                    lifecycle_state = "FADE_OUT"
                    state_start_time = t
        elif lifecycle_state == "FADE_OUT":
            elapsed = t - state_start_time
            if elapsed < fade_duration:
                global_fade_val = 1.0 - (elapsed / fade_duration)
            else:
                global_fade_val = 0.0
                running = False # 动画最终完成，结束主循环
                
        prog['global_fade'].value = max(0.0, min(1.0, global_fade_val))

        prog['time'].value = t

        ctx.clear(0.0, 0.0, 0.0, 0.0)
        
        # Draw frame natively onto GUI
        tex_bg.use(0)
        tex_text.use(1)
        vao.render(moderngl.TRIANGLE_STRIP)

        pygame.display.flip()
        
        # After the first successful render loop, make the window visible.
        # Then reveal the window without taking focus from the user's active app.
        if sys.platform == "win32" and user32.IsWindowVisible(hwnd) == 0:
            user32.ShowWindow(hwnd, 8) # SW_SHOWNA (Show without activating)
            # user32.SetForegroundWindow(hwnd)
            # user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0040 | 0x0010 | 0x0002 | 0x0001)

# --- 强行夺取前台权限 ---
            # 增量代码：此时进程已拥有权限，调用此函数刷新主窗口的 Z-Order 且不触发黑屏闪烁
            user32.BringWindowToTop(hwnd)
            # 桥接窗口使命完成，销毁之
            if 'h_bridge' in locals():
                user32.DestroyWindow(h_bridge)
# ----------------------

        # Cap logic loop max efficiency. High frame rate enhances liquid smooth feel.
        clock.tick(60) 

    pygame.quit()

def check_dependencies():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    required_files = [
        "config.json",
        "shader.glsl",
        os.path.join("assets", "lightning.png")
    ]
    
    missing = []
    
    for f in required_files:
        # if not os.path.exists(os.path.join(base_dir, f)):
        if not os.path.exists(os.path.join(f)):
            missing.append(f)
            
    if missing:
        msg = "缺少依赖文件:\n" + "\n".join(missing)
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, "错误", 0x10)
        except:
            print(msg)
        sys.exit(1)

    # # config.json handling
    # config_default_path = os.path.join(base_dir, "config-default.json")
    # config_path = os.path.join(base_dir, "config.json")
    
    # should_copy_default = False
    
    # if not os.path.exists(config_path):
    #     if os.path.exists(config_default_path):
    #          should_copy_default = True
    # elif os.path.exists(config_default_path):
    #     # Check for missing keys
    #     try:
    #         with open(config_default_path, "r", encoding="utf-8") as f:
    #             default_cfg = json.load(f)
    #         with open(config_path, "r", encoding="utf-8") as f:
    #             current_cfg = json.load(f)
            
    #         def check_keys(def_c, cur_c):
    #             for k, v in def_c.items():
    #                 if k not in cur_c:
    #                     return True
    #                 if isinstance(v, dict) and isinstance(cur_c[k], dict):
    #                      if check_keys(v, cur_c[k]):
    #                          return True
    #             return False

    #         if check_keys(default_cfg, current_cfg):
    #             should_copy_default = True
                
    #     except Exception:
    #          # If cant parse, assume broken
    #          should_copy_default = True
    
    # if should_copy_default and os.path.exists(config_default_path):
    #     try:
    #         import shutil
    #         shutil.copy2(config_default_path, config_path)
    #     except Exception as e:
    #         msg = f"无法重置配置文件: {e}"
    #         try:
    #             ctypes.windll.user32.MessageBoxW(0, msg, "错误", 0x10)
    #         except:
    #             print(msg)


if __name__ == "__main__":
    check_dependencies()
    main()


