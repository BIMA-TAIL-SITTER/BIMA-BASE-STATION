import re

with open('src/app/globals.css', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all .attitude-indicator blocks with the transparent one
content = re.sub(r'\.attitude-indicator\s*\{[^}]+\}', '.attitude-indicator {\n  width: clamp(100px, 12vw, 170px);\n  height: clamp(70px, 8.5vw, 120px);\n  border-radius: var(--radius-lg);\n  margin: 5px auto 15px auto;\n  position: relative;\n  overflow: hidden;\n  background-color: transparent;\n  border: none;\n  box-shadow: none;\n}', content)

# Fix duplicate telem-panel::before
content = content.replace('/* Subtle top accent shimmer */\n.telem-panel::before {\n  content: "";\n\n/* Subtle top accent shimmer */\n.telem-panel::before {\n  content: "";\n  position: absolute;\n  top: 0;\n  left: 20%;\n  right: 20%;\n  height: 1px;\n  background: linear-gradient(90deg, transparent, rgba(var(--accent-rgb), 0.15), transparent);\n  pointer-events: none;\n}', '/* Subtle top accent shimmer */\n.telem-panel::before {\n  content: "";\n  position: absolute;\n  top: 0;\n  left: 20%;\n  right: 20%;\n  height: 1px;\n  background: linear-gradient(90deg, transparent, rgba(var(--accent-rgb), 0.15), transparent);\n  pointer-events: none;\n}')

with open('src/app/globals.css', 'w', encoding='utf-8') as f:
    f.write(content)
