# BIMA GCS — Soft Mission Control Design System

## Design Philosophy

**Soft Mission Control** — Dashboard kontrol misi yang tenang, modern, ramah, namun tetap presisi dan profesional. Menghindari estetika military HUD yang agresif, tajam, dan kaku.

### Core Principles

1. **Softness over Sharpness** — Rounded corners konsisten (8-16px), tidak ada sudut 90°
2. **Calm Neutrality** — Palet netral hangat, tidak dingin/steril, tidak neon
3. **Breathing Room** — Whitespace generous, density yang nyaman dibaca
4. **Gentle Depth** — Shadow lembut (ambient + key), bukan hard drop shadow
5. **Natural Motion** — Easing natural (ease-out-expo, spring), durasi 200-400ms
6. **Quiet Hierarchy** — Typography, spacing, dan weight yang bicara, bukan border tebal

---

## Color Tokens

### Neutral Foundation (Warm Gray Scale)

| Token | Light | Dark | Use |
|-------|-------|------|-----|
| `--bg-base` | `#FAFAF8` | `#0E0E0E` | Background utama |
| `--bg-elevated` | `#FFFFFF` | `#161616` | Panel, card, modal |
| `--bg-hover` | `#F2F2EF` | `#1E1E1E` | Hover state |
| `--bg-pressed` | `#E8E8E3` | `#262626` | Active/pressed |
| `--border-subtle` | `#E4E4DD` | `#2A2A2A` | Border default |
| `--border-emphasis` | `#D0D0C8` | `#3A3A3A` | Border focus/emphasis |
| `--text-primary` | `#1A1A18` | `#F5F5F0` | Text utama |
| `--text-secondary` | `#52524E` | `#A8A8A0` | Text sekunder, label |
| `--text-muted` | `#8C8C86` | `#787872` | Placeholder, disabled, hint |
| `--text-inverse` | `#FAFAF8` | `#0E0E0E` | Text on colored bg |

### Semantic Colors (Soft, Not Neon)

| Token | Light | Dark | Use |
|-------|-------|------|-----|
| `--info` | `#3B82F6` | `#60A5FA` | Info, connection, telemetry live |
| `--info-bg` | `#EFF6FF` | `#1E3A5F` | Info background |
| `--success` | `#16A34A` | `#4ADE80` | Connected, armed, nominal |
| `--success-bg` | `#F0FDF4` | `#14532D` | Success background |
| `--warning` | `#F59E0B` | `#FBBF24` | Caution, stale, pending |
| `--warning-bg` | `#FFFBEB` | `#451A03` | Warning background |
| `--danger` | `#EF4444` | `#F87171` | Disconnected, critical, destructive |
| `--danger-bg` | `#FEF2F2` | `#450A0A` | Danger background |

### UAV Identity Colors (Muted, Identifiable)

| UAV | Token | Light | Dark | Use |
|-----|-------|-------|------|-----|
| 01 | `--uav-01` | `#3B82F6` | `#60A5FA` | Blue - Fixed wing 1 |
| 02 | `--uav-02` | `#F59E0B` | `#FBBF24` | Amber - Fixed wing 2 |
| 03 | `--uav-03` | `#F97316` | `#FB923C` | Orange - Copter 1 |
| 04 | `--uav-04` | `#EC4899` | `#F472B6` | Pink - Copter 2 |

*Identity colors hanya untuk: UAV badge, track line di peta, accent kecil pada panel UAV tersebut. Tidak dipakai untuk semantic state global.*

---

## Typography

### Font Stack
- **Display/UI**: `Inter Variable` (self-hosted via `next/font`) — clean, readable, modern
- **Mono/Data**: `JetBrains Mono Variable` — coordinates, timestamps, parameter IDs

### Type Scale

| Role | Size | Weight | Line Height | Letter Spacing | Use |
|------|------|--------|-------------|----------------|-----|
| `--text-xs` | 11px | 400 | 1.4 | +0.02em | Labels, badges, metadata |
| `--text-sm` | 13px | 400 | 1.5 | +0.01em | Secondary text, small metrics |
| `--text-base` | 15px | 400 | 1.6 | 0 | Body, default UI text |
| `--text-lg` | 17px | 400 | 1.5 | -0.01em | Emphasized values |
| `--text-xl` | 20px | 500 | 1.4 | -0.01em | Panel titles, key metrics |
| `--text-2xl` | 28px | 600 | 1.2 | -0.02em | Hero numbers (altitude, speed) |
| `--text-3xl` | 40px | 600 | 1.1 | -0.02em | Large display (compass heading) |

### Mono Scale (Data)

| Role | Size | Weight | Use |
|------|------|--------|-----|
| `--mono-xs` | 11px | 400 | Timestamps, port numbers |
| `--mono-sm` | 13px | 400 | Coordinates, parameter values |
| `--mono-base` | 15px | 400 | Editable fields, precise data |
| `--mono-lg` | 20px | 500 | Primary telemetry values |

---

## Spacing & Layout

### Base Unit: 4px

| Token | Value | Use |
|-------|-------|-----|
| `--space-1` | 4px | Micro gap, icon-text |
| `--space-2` | 8px | Compact gap, padding small |
| `--space-3` | 12px | Default gap, padding medium |
| `--space-4` | 16px | Standard padding, card gap |
| `--space-5` | 20px | Section padding |
| `--space-6` | 24px | Panel padding, major gap |
| `--space-8` | 32px | Page section gap |
| `--space-10` | 40px | Major layout gap |
| `--space-12` | 48px | Hero section gap |

### Layout Grid
- **Dashboard**: 3 kolom resizable (left: video+telemetry, center: map, right: copter telemetry)
- **Splitter width**: 8px (transparent hit area 16px)
- **Column min/max**: Left 280-520px, Center flexible, Right 260-480px
- **Border radius**: `--radius-sm` 6px, `--radius-md` 10px, `--radius-lg` 14px, `--radius-xl` 18px, `--radius-full` 9999px

---

## Shadow System (Layered, Soft)

| Token | Value | Use |
|-------|-------|-----|
| `--shadow-xs` | `0 1px 2px rgba(0,0,0,0.03)` | Subtle depth, inline elements |
| `--shadow-sm` | `0 2px 4px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03)` | Card resting, panel |
| `--shadow-md` | `0 4px 8px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.03)` | Elevated card, modal |
| `--shadow-lg` | `0 8px 16px rgba(0,0,0,0.06), 0 4px 8px rgba(0,0,0,0.04)` | Modal, dropdown, tooltip |
| `--shadow-xl` | `0 16px 32px rgba(0,0,0,0.08), 0 8px 16px rgba(0,0,0,0.05)` | Overlay, sheet |
| `--shadow-focus` | `0 0 0 3px var(--info-bg)` | Focus ring (light) / `0 0 0 3px rgba(96,165,250,0.3)` (dark) |

*Dark mode shadows menggunakan `rgba(0,0,0,alpha)` yang lebih tinggi karena background gelap.*

---

## Border Radius Scale

| Token | Value | Use |
|-------|-------|-----|
| `--radius-sm` | 6px | Buttons, badges, small inputs |
| `--radius-md` | 10px | Cards, panels, modals |
| `--radius-lg` | 14px | Major panels, video containers |
| `--radius-xl` | 18px | Full-screen containers |
| `--radius-full` | 9999px | Pills, avatar, progress |

---

## Motion & Animation

### Easing Curves
- `--ease-out-expo`: `cubic-bezier(0.16, 1, 0.3, 1)` — natural, graceful (default)
- `--ease-out-quart`: `cubic-bezier(0.25, 1, 0.5, 1)` — slightly faster
- `--ease-spring`: `cubic-bezier(0.34, 1.56, 0.64, 1)` — playful, for toggles
- `--ease-in-out`: `cubic-bezier(0.4, 0, 0.2, 1)` — standard transitions

### Duration Scale
- `--duration-fast`: 120ms — hover, press, small toggle
- `--duration-base`: 200ms — default transition
- `--duration-smooth`: 300ms — panel expand, modal enter
- `--duration-slow`: 400ms — page transition, complex layout shift

### Motion Principles
- **Respect `prefers-reduced-motion`** — disable non-essential animation
- **No ambient motion** — hanya response to user action / state change
- **Staggered entrance** — 40ms delay per item untuk list/grid
- **Transform + opacity only** — avoid layout thrashing

---

## Component Patterns

### Panel / Card
```
Background: var(--bg-elevated)
Border: 1px solid var(--border-subtle)
Border-radius: var(--radius-lg) (14px)
Padding: var(--space-6) (24px)
Shadow: var(--shadow-sm)
Hover: shadow var(--shadow-md), border var(--border-emphasis)
Transition: all var(--duration-base) var(--ease-out-expo)
```

### Button
```
Height: 40px (default), 32px (sm), 48px (lg)
Padding: 0 var(--space-4) / 0 var(--space-5) / 0 var(--space-6)
Border-radius: var(--radius-md) (10px)
Font: var(--text-sm) / var(--text-base) / var(--text-base)
Weight: 500
Transition: all var(--duration-fast) var(--ease-out-quart)

Variants:
- Primary: bg var(--info), text white, hover darker
- Secondary: bg var(--bg-hover), border var(--border-subtle), text primary
- Ghost: transparent, hover bg var(--bg-hover)
- Danger: bg var(--danger), text white
- Pill: border-radius var(--radius-full)
```

### Input / Select
```
Height: 40px
Padding: 0 var(--space-3)
Border: 1px solid var(--border-subtle)
Border-radius: var(--radius-md)
Background: var(--bg-base)
Color: var(--text-primary)
Placeholder: var(--text-muted)
Focus: border var(--info), shadow var(--shadow-focus), outline none
Error: border var(--danger), focus shadow var(--danger-bg)
Disabled: opacity 0.5, cursor not-allowed
```

### Badge / Pill
```
Padding: 2px 8px (xs), 4px 10px (sm), 6px 12px (base)
Border-radius: var(--radius-full)
Font: var(--text-xs) / var(--text-sm) / var(--text-sm)
Weight: 500
```

### Divider / Separator
```
Height/Width: 1px
Color: var(--border-subtle)
Margin: var(--space-4) 0
```

### Tooltip
```
Background: var(--text-primary) / rgba(26,26,24,0.92)
Color: var(--bg-base)
Padding: var(--space-2) var(--space-3)
Border-radius: var(--radius-sm)
Font: var(--text-xs)
Shadow: var(--shadow-lg)
Arrow: 6px
Animation: fade + scale(0.95→1) var(--duration-fast)
```

---

## Dashboard Layout Spec

### Header Bar (Top)
- Height: 56px
- Background: `var(--bg-elevated)` + backdrop-blur `8px` (sticky)
- Border-bottom: 1px `var(--border-subtle)`
- Padding: 0 `var(--space-6)`
- Logo + title: `var(--text-xl)` weight 600
- Connection status: pill badge
- UAV selector: segmented control
- Theme toggle: icon button

### Left Column (Fixed Wing Stack)
- Width: 280-520px (resizable)
- Gap: `var(--space-4)` between rows
- Each row: Video panel (16:9) + Telemetry panel side by side on desktop, stacked on mobile
- Video panel: `var(--radius-lg)`, overflow hidden, bg `var(--instrument-void)`
- Telemetry panel: `var(--radius-lg)`, bg `var(--bg-elevated)`

### Center Column (Map)
- Flexible width (min 400px)
- Map container: `var(--radius-lg)`, overflow hidden
- Segmented telemetry rail: thin accent bar (2px) di kiri/kanan peta, color `var(--signal)` hanya saat UAV selected
- UAV tracks: lines dengan identity color, opacity 0.6
- Waypoints: small circles, identity color

### Right Column (Copter Telemetry)
- Width: 260-480px (resizable)
- Stacked copter panels (UAV 3, UAV 4)
- Each panel: `var(--radius-lg)`, bg `var(--bg-elevated)`
- Compass: large, soft, interactive
- Metric grid: clean, aligned, mono font untuk values

### Splitters
- Width: 8px visual, 16px hit area
- Background: transparent
- Hover: `var(--border-emphasis)` vertical line center
- Drag: `var(--info)` line, panel resize real-time
- Keyboard accessible: Arrow keys ±16px, Shift+Arrow ±48px
- Double-click: reset to default

---

## Responsive Breakpoints

| Breakpoint | Width | Layout Change |
|------------|-------|---------------|
| `--bp-sm` | 640px | Stack video+telemetry rows, header compact |
| `--bp-md` | 900px | Right column collapsible, UAV selector dropdown |
| `--bp-lg` | 1280px | Default 3-column layout |
| `--bp-xl` | 1536px | Wider columns, larger map |
| `--bp-2xl` | 1920px | Max comfortable width |

---

## Accessibility

- **Contrast**: Minimum 4.5:1 (AA) untuk text, 3:1 untuk UI elements
- **Focus**: Visible focus ring `var(--shadow-focus)` pada semua interactive elements
- **Keyboard**: Semua fungsi reachable via keyboard (Tab, Arrow, Enter, Escape)
- **Screen readers**: ARIA labels, live regions untuk telemetry updates, roles yang tepat
- **Reduced motion**: `@media (prefers-reduced-motion: reduce)` disable transitions/animations
- **Color blindness**: Tidak rely hanya pada warna — icon + label + pattern

---

## Implementation Notes

### CSS Architecture
```
globals.css
├── @import "tailwindcss"
├── Design tokens (:root, [data-theme="dark"])
├── Base reset
├── Typography utilities
├── Layout utilities (grid, flex, spacing)
├── Component primitives (button, input, card, badge, etc)
├── Dashboard layout (header, columns, splitters, panels)
├── Map & video specific
├── Telemetry components
├── Animations & keyframes
├── Responsive overrides
├── Reduced motion
├── Print styles
└── Utility overrides
```

### Tailwind Integration
- Gunakan `@theme` untuk design tokens (Tailwind v4)
- Custom utilities untuk patterns yang repeatable
- Avoid arbitrary values — pakai design tokens
- Component classes untuk complex patterns (`.panel`, `.btn-primary`, `.metric-grid`)

### React Components
- CSS Modules atau Tailwind className (pilih satu, konsisten)
- `className` composition via `clsx` / `tailwind-merge`
- CSS variables untuk dynamic theming (UAV identity colors)
- Framer Motion atau CSS transitions untuk animasi (prefer CSS untuk performance)

---

## Migration Checklist

- [ ] Replace `globals.css` dengan design system baru
- [ ] Update `layout.tsx` dengan header bar baru
- [ ] Redesign `page.tsx` layout 3 kolom
- [ ] Rewrite `VideoPanel` — soft corners, clean controls
- [ ] Rewrite `CopterTelemetryPanel` — compass, metric grid
- [ ] Rewrite `MavlinkHeader` — pill badge, soft
- [ ] Rewrite `TelemetryStats` — clean data display
- [ ] Rewrite `PetaOfflineUav` — soft map container, rails
- [ ] Rewrite `ConnectionSetupModal` — centered, friendly
- [ ] Update `useGCSStore` / hooks jika perlu
- [ ] Test light/dark mode
- [ ] Test responsive
- [ ] Test keyboard navigation
- [ ] Test reduced motion
- [ ] Polish: micro-interactions, loading states, empty states