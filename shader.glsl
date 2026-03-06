#version 330 core

uniform sampler2D tex_bg;
uniform sampler2D tex_text;
uniform float time;
uniform vec2 resolution;
uniform vec3 overlay_color;
uniform float alpha;
uniform int direction; // 1=Left-L, 2=Right-L, 3=Top, 4=Bottom, 5=Left, 6=Right
uniform float bg_darkness;
uniform float bg_darkness_new;
uniform float ripple_distortion;
uniform float ripple_speed;
uniform float ring_scale;
uniform float inner_radius;
uniform float outer_radius;
uniform float particle_density;
uniform float particle_speed;
uniform float particle_enabled; // 1.0 for true, 0.0 for false
uniform float particle_wave_ratio; 
uniform float particle_radius_offset;
uniform float particle_brightness;
uniform float text_scale;
uniform float line_thickness;
uniform float l_shape_y_offset;
uniform float l_shape_curve_radius;
uniform float global_fade; // 0.0 to 1.0 用于控制全局所有的渐隐渐显

in vec2 uvs;
out vec4 f_color;

// Hash functions for PRNG
float hash(vec2 p) {
    vec3 p3  = fract(vec3(p.xyx) * .1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

// Seamless Value Noise
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float res = mix(
        mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
        mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x),
        f.y
    );
    return res;
}

// Fractal Brownian Motion for Fluid effects
float fbm(vec2 p) {
    float f = 0.0;
    float amp = 0.5;
    mat2 m = mat2(1.6,  1.2, -1.2,  1.6);
    for (int i = 0; i < 4; i++) {
        f += amp * noise(p);
        p = m * p;
        amp *= 0.5;
    }
    return f;
}

// Procedural text glowing processor
float get_text_glow(vec2 u, float radius) {
    float a = 0.0;
    float steps = 12.0;
    for(float i = 0.0; i < 6.28318; i += 6.28318 / steps) {
        a += texture(tex_text, u + vec2(cos(i), sin(i)) * radius).a;
    }
    return a / steps;
}

// Function to generate scattered particles
float get_particles(vec2 pos, float time_val, float freq, float wave_spd, float p_density, float p_speed) {
    float d = length(pos);
    float in_r = (inner_radius - particle_radius_offset) * ring_scale;
    float out_r = (outer_radius + particle_radius_offset) * ring_scale;
    
    // Bounds check to save performance
    if (d < in_r - 0.05 || d > out_r + 0.05) return 0.0;
    
    float angle = atan(pos.y, pos.x);
    float a_norm = (angle + 3.14159265) / 6.2831853;
    float r_norm = clamp((d - in_r) / (out_r - in_r), 0.0, 1.0);
    
    // Wave mask (3 ring waves = 1 particle wave)
    float part_wave_phase = d * freq - time_val * wave_spd;
    float wave_mask = smoothstep(0.2, 0.9, sin(part_wave_phase) * 0.5 + 0.5);
    
    // Particle spawner grid setup
    float spokes = max(10.0, floor(p_density));
    float radial_levels = max(5.0, floor(p_density * 0.6)); 
    
    // Outward drift movement
    float drift = time_val * p_speed; 
    
    float cx = a_norm * spokes;
    float cy = d * radial_levels - drift * radial_levels;
    
    vec2 cell_id = vec2(floor(cx), floor(cy));
    cell_id.x = mod(cell_id.x, spokes); // Seamless polar wrapping
    
    float n = hash(cell_id);
    if (n > 0.85) { 
        vec2 local_pos = vec2(fract(cx), fract(cy));
        // Randomize center loosely within cell
        vec2 center = vec2(hash(cell_id + 11.1), hash(cell_id + 22.2)) * 0.6 + 0.2;
        
        // Approximate aspect ratio correction for spherical distance
        vec2 phys_delta = vec2((local_pos.x - center.x) * ((6.28318 * d) / spokes), 
                               (local_pos.y - center.y) / radial_levels);
        float dist = length(phys_delta);
        
        // Randomize sizes
        float p_size = 0.0015 + n * 0.0025;
        // Make very soft glowing spheres, 并由此引入自定义亮度调节 particle_brightness
        float glow = smoothstep(p_size, 0.0, dist) * ((n - 0.85) * 6.6) * particle_brightness;
        
        // Alpha fading from inner circle to outer circle
        float fade = smoothstep(0.0, 0.15, r_norm) * smoothstep(1.0, 0.7, r_norm);
        
        return glow * fade * wave_mask;
    }
    return 0.0;
}

void main() {
    vec2 uv = uvs;
    
    // Correct aspect ratio scaling, making the center strictly p = vec2(0, 0)
    vec2 p = (uv - 0.5) * vec2(resolution.x / resolution.y, 1.0);
    
    vec4 bg = texture(tex_bg, uv);
    vec4 col = bg;
    
    // Configured transparency (dark overlay for outer space representation)
    col.rgb = mix(col.rgb, vec3(0.0), bg_darkness);
    
    // ---- 新增：全屏无差别底层压暗 ----
    // 可以应对纯白背景过曝的问题，并直接给所有采样到的背景像素附上暗度
    col.rgb = mix(col.rgb, vec3(0.0), bg_darkness_new);
    // 这里顺便降低原贴图在折射时的基础亮度，保障纯白背景下色散和高光能够显示出颜色
    vec3 base_tx_color = mix(bg.rgb, vec3(0.0), bg_darkness_new);

    // Dimension scales mapping to center annulus format
    float inner_r = inner_radius * ring_scale;
    float outer_r = outer_radius * ring_scale; // Expand slightly for smoother outer fading
    float d_center = length(p);

    // Perfect fade out function matching exactly 0.0 at the absolute edges.
    // Uses smoothstep to create a seamless bell-like envelope over the ring context.
    float fade_envelope = smoothstep(inner_r - 0.01 * ring_scale, inner_r + 0.05 * ring_scale, d_center) * 
                          smoothstep(outer_r, outer_r - 0.12 * ring_scale, d_center);

    // Organic ripples modification base form FBM to make it look like chaotic water
    float n_env = fbm(p * (5.0 / ring_scale) - time * 0.8 * ripple_speed);
    
    // Multi-layered spreading water ripple mapping
    // Combining a dominant frequency + fine details for a multi-scale splash
    float wave_freq = 80.0 / ring_scale;
    float wave_speed = 12.0 * ripple_speed;
    float wave_phase = d_center * wave_freq - time * wave_speed;
    
    float wave = sin(wave_phase + n_env * 2.0) * 0.5 + 
                 sin(wave_phase * 1.5 - time * 5.0 * ripple_speed) * 0.3 + 
                 cos(wave_phase * 0.5 - time * 8.0 * ripple_speed) * 0.2;

    // Apply adjustable ripple_distortion (from uniform)
    // The distortion entirely fades out using 'fade_envelope' for perfect boundary matching
    vec2 offset_dir = normalize(p);
    vec2 normal = offset_dir * wave * fade_envelope * ripple_distortion;

    // A simpler mask just for the overall effect presence (like tints, glowing)
    // 扩展遮罩范围，为超出的粒子腾出完整的渲染空间，防止刚出内圆外圆就被强制抹除
    float p_mask_in = (inner_radius - particle_radius_offset) * ring_scale;
    float p_mask_out = (outer_radius + particle_radius_offset) * ring_scale;
    float ring_mask = smoothstep(p_mask_in - 0.02, p_mask_in + 0.02, d_center) * 
                      smoothstep(p_mask_out + 0.02, p_mask_out - 0.02, d_center);

    // Physical dispersion index
    float dist_strength = 0.1 + 0.02 * n_env; 
    if (ring_mask > 0.001) {
        // Red, Green, Blue Chromatic Abberation channels based on layered normal
        vec2 ofs_r = normal * dist_strength * 1.5;
        vec2 ofs_g = normal * dist_strength * 1.0;
        vec2 ofs_b = normal * dist_strength * 0.5;
        
        // ---- 新增：粒子跟随折射并附加底层 ----
        // 将 UV 空间的偏移坐标映射回基于中心物理尺度的 P 空间
        vec2 aspect = vec2(resolution.x / resolution.y, 1.0);
        vec2 p_r = (clamp(uv + ofs_r, 0.0, 1.0) - 0.5) * aspect;
        vec2 p_g = (clamp(uv + ofs_g, 0.0, 1.0) - 0.5) * aspect;
        vec2 p_b = (clamp(uv + ofs_b, 0.0, 1.0) - 0.5) * aspect;
        
        // 频率与波速同步为水波的比率控制（由配置文件 particle_wave_ratio 提供）
        float p_freq = wave_freq / particle_wave_ratio;
        float p_w_spd = wave_speed / particle_wave_ratio;
        
        vec3 part_color = vec3(0.0);
        if (particle_enabled > 0.5) {
            // 分别对含有色散变形的坐标进行三原色粒子遮罩生成，以保证它们如同存在于玻璃层下方一样参与色散折射
            float part_r = get_particles(p_r, time, p_freq, p_w_spd, particle_density, particle_speed);
            float part_g = get_particles(p_g, time, p_freq, p_w_spd, particle_density, particle_speed);
            float part_b = get_particles(p_b, time, p_freq, p_w_spd, particle_density, particle_speed);
            
            // 移除 fade_envelope 以允许粒子突破原水波纹的边界，并乘上 2.0 直接提高整体主光亮度
            part_color = vec3(part_r, part_g, part_b) * overlay_color * 2.0;
        }
        // ------------------------------------
        
        // Sampling under-the-window UI texture mappings with distorted coordinates
        // 并通过将提取出来的折射背景也叠加 bg_darkness_new 压暗，确保纯白色背景发光元素可见
        float r = texture(tex_bg, clamp(uv + ofs_r, 0.0, 1.0)).r;
        float g = texture(tex_bg, clamp(uv + ofs_g, 0.0, 1.0)).g;
        float b = texture(tex_bg, clamp(uv + ofs_b, 0.0, 1.0)).b;
        
        // 我们将折射下的桌面压暗之后，额外光加上受到相同折射扰动的底层粒子发光
        vec3 refracted_bg = mix(vec3(r, g, b), vec3(0.0), bg_darkness_new) + part_color;
        
        // Dynamic caustic high intensity highlights on wave crests
        // Because wave domain is -1.0 ~ +1.0, map and intensify the peaks
        float caustics = pow(max(0.0, wave * n_env + 0.5), 3.0) * 0.8;
        vec3 energy_color = overlay_color * caustics * alpha * fade_envelope;
        
        vec3 ring_tint = overlay_color * 0.15 * alpha * fade_envelope;
        
        // Blend effectively over the darkened background using the general ring mask
        // When normal approaches vec2(0), refracted_bg == col.rgb.
        col.rgb = mix(col.rgb, refracted_bg + energy_color + ring_tint, ring_mask);
    }

    float flow_mask = 0.0;
    float along = 0.0;
    float across = 0.0;
    
    // Handle specific beam orientation flow matrix
    if (direction == 5) { // Left
        along = -(p.x);
        across = p.y;
    } else if (direction == 6) { // Right
        along = p.x;
        across = p.y;
    } else if (direction == 3) { // Bottom
        along = p.y;
        across = p.x;
    } else if (direction == 4) { // Top
        along = -(p.y);
        across = p.x;
    } else if (direction == 1) { // Left L-Shape
        float R = l_shape_curve_radius;
        float Y0 = l_shape_y_offset;
        vec2 C = vec2(-R, Y0 - R);
        vec2 q = p - C;
        
        if (q.x > 0.0 && q.y > 0.0) {
            // Corner
            across = length(q) - R;
            float theta = atan(q.y, q.x); // 0 to pi/2
            along = (Y0 - R) + R * theta;
        } else if (q.x <= 0.0 && q.y >= q.x) {
            // Horizontal
            across = p.y - Y0;
            along = (Y0 - R) + R * 1.57079632 - q.x;
        } else {
            // Vertical
            across = p.x;
            along = p.y;
        }
    } else if (direction == 2) { // Right L-Shape
        float R = l_shape_curve_radius;
        float Y0 = l_shape_y_offset;
        vec2 C = vec2(R, Y0 - R);
        vec2 q = p - C;
        
        if (q.x < 0.0 && q.y > 0.0) {
            // Corner
            across = length(q) - R;
            float theta = atan(q.y, -q.x); // 0 to pi/2
            along = (Y0 - R) + R * theta;
        } else if (q.x >= 0.0 && q.y >= -q.x) {
            // Horizontal
            across = p.y - Y0;
            along = (Y0 - R) + R * 1.57079632 + q.x;
        } else {
            // Vertical
            across = -p.x;
            along = p.y;
        }
    }
    
    flow_mask = step(inner_r, along);
    
    // Calculate distance to convergence edge
    float edge_dist = along - inner_r;
    
    // As it gets extremely close to the inner radius (edge_dist approaches 0), it expands smoothly. 
    // Uses an exponential or quadratic curve to only expand at the very end.
    float flare_out = smoothstep(0.06, 0.0, edge_dist) * 2.0; 
    float dynamic_thickness = line_thickness * (1.0 + flare_out);
    
    flow_mask *= smoothstep(dynamic_thickness, dynamic_thickness * 0.5, abs(across));
    
    // Particle energy line simulation logic
    if (flow_mask > 0.001) {
        float p_time = time * 3.5;
        vec2 part_uv = vec2(along * 10.0 + p_time, across * 30.0);
        
        // Fluid continuous noise logic instead of sparse discrete structure
        float wave1 = sin(part_uv.x) * 0.5 + 0.5;
        float wave2 = sin(part_uv.x * 2.3 + part_uv.y * 3.1 + time) * 0.5 + 0.5;
        
        float noise_val = fbm(part_uv * 0.8);
        
        // Build a consistently vibrant glowing beam with moving ripples inside
        float base_glow = 0.15; // 降低基础亮度，使其不再刺眼
        float energetic_pulse = (wave1 * 0.5 + wave2 * 0.5);
        
        // 增加对比度，让内部水波纹/流动的纹理更加显眼，而不是变成一片纯白
        float structural = mix(base_glow, 0.8, energetic_pulse * smoothstep(0.4, 0.9, noise_val));
        
        // 降低边缘发光强度，使其更柔和
        float edge_glow = pow(max(0.0, 1.0 - abs(across) / dynamic_thickness), 3.0) * 0.4;
        
        float intensity = structural + edge_glow;
        
        // It fades out fully as it meets the battery center limit, no burning hot-spots.
        // It does not fade to nothing purely down the wire, so outer bounds stay vibrant.
        float distance_fade = smoothstep(0.0, 0.08, edge_dist);
        
        // ---- 新增：充电线内部光线扭曲与色散 ----
        // 构造代表水管横截面隆起的凸度 (0为边缘，1为中心)
        float cross_profile = max(0.0, 1.0 - abs(across) / dynamic_thickness);
        
        // 基于水流时间和空间坐标构造波动态虚拟法线，使其随速度(p_time)和流动(part_uv.x / noise_val)发生偏移
        float distort_angle = part_uv.x * 0.5 + noise_val * 6.28; 
        
        // 结合当前点方向和流体波动的旋转向量，制造涌动折射感
        vec2 tube_normal = normalize(p + vec2(0.001)) * cross_profile + vec2(cos(distort_angle), sin(distort_angle)) * energetic_pulse;
        tube_normal = normalize(tube_normal) * cross_profile * energetic_pulse;
        
        // 计算类似于水波纹中心的色散偏移强度
        float tube_dist_strength = 0.06 * distance_fade * (0.3 + 0.7 * noise_val);
        
        vec2 ofs_r_tube = tube_normal * tube_dist_strength * 1.5;
        vec2 ofs_g_tube = tube_normal * tube_dist_strength * 1.0;
        vec2 ofs_b_tube = tube_normal * tube_dist_strength * 0.5;
        
        // 利用带有色散偏差的坐标去对窗外真实背景进行采样 (RGB三色分离)
        // 同样将提取出来的色散背景也进行全屏压暗，防止在纯白桌面叠加发光色时全部被过曝截断为白色
        float r_tube = texture(tex_bg, clamp(uv + ofs_r_tube, 0.0, 1.0)).r;
        float g_tube = texture(tex_bg, clamp(uv + ofs_g_tube, 0.0, 1.0)).g;
        float b_tube = texture(tex_bg, clamp(uv + ofs_b_tube, 0.0, 1.0)).b;
        vec3 refracted_tube_bg = mix(vec3(r_tube, g_tube, b_tube), vec3(0.0), bg_darkness_new);
        
        // 按照横截面轮廓平滑替换原有背景为色散透镜背景（越到管子边缘平滑交接避免生硬断层）
        float mix_weight = flow_mask * (cross_profile * distance_fade);
        col.rgb = mix(col.rgb, refracted_tube_bg, mix_weight);
        // ------------------------------------
        
        // 最后叠加发光颜色，保持线条的高亮光线和噪点明暗对比
        vec3 flow_color = overlay_color * intensity * alpha * distance_fade * 1.5;
        
        col.rgb += flow_color * flow_mask;
    }

    // Centered percentage texts execution wrapper
    // We map the 800x800 text texture directly to the screen center
    vec2 text_uv = (uv - 0.5) * vec2(resolution.x / 800.0, resolution.y / 800.0) / text_scale + 0.5;
    if (text_uv.x >= 0.0 && text_uv.x <= 1.0 && text_uv.y >= 0.0 && text_uv.y <= 1.0) {
        vec4 tcol = texture(tex_text, text_uv);
        if (tcol.a > 0.0) {
            col.rgb = mix(col.rgb, tcol.rgb, tcol.a);
        }
    }

    // 最终全局渐隐控制：通过将加工过的效果画面与未加工的原始截图平滑混合，实现完全融入背景或者展现。
    f_color = vec4(mix(bg.rgb, col.rgb, global_fade), 1.0);
}