"""
Script to fix the OPENAI_API_KEY in .env file
This ensures the key is on a single line and matches the working key
"""
import os
from pathlib import Path

# The working API key from environment variable
WORKING_KEY = os.getenv("OPENAI_API_KEY", "")

env_file = Path(__file__).parent / ".env"

print("Fixing .env file...")
print("=" * 60)

if not env_file.exists():
    print(f"Creating new .env file at {env_file}")
    with open(env_file, 'w') as f:
        f.write(f"OPENAI_API_KEY={WORKING_KEY}\n")
        f.write("OPENAI_MODEL=gpt-3.5-turbo\n")
    print("✅ Created .env file with correct API key")
else:
    print(f"Reading existing .env file...")
    with open(env_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check current key
    lines = content.split('\n')
    current_key = None
    for line in lines:
        if line.startswith('OPENAI_API_KEY='):
            # Get the key value (handle multi-line)
            key_part = line.split('=', 1)[1] if '=' in line else ''
            # Collect all parts if split across lines
            if key_part:
                current_key = key_part
                # Check if next lines continue the key
                idx = lines.index(line)
                for next_line in lines[idx+1:]:
                    if next_line.strip() and not next_line.strip().startswith('#') and '=' not in next_line:
                        current_key += next_line.strip()
                    else:
                        break
            break
    
    if current_key:
        # Remove whitespace to compare
        current_key_clean = "".join(current_key.split())
        working_key_clean = "".join(WORKING_KEY.split())
        
        print(f"Current key length: {len(current_key_clean)}")
        print(f"Working key length: {len(working_key_clean)}")
        
        if current_key_clean == working_key_clean:
            print("✅ API key already correct!")
        else:
            print("⚠️  API key is different, updating...")
            # Replace the key
            # Remove old OPENAI_API_KEY line(s)
            new_lines = []
            skip_until_newline = False
            for line in lines:
                if line.startswith('OPENAI_API_KEY='):
                    new_lines.append(f"OPENAI_API_KEY={WORKING_KEY}")
                    skip_until_newline = True
                elif skip_until_newline:
                    # Skip continuation lines
                    if line.strip() and not line.strip().startswith('#') and '=' not in line:
                        continue
                    else:
                        skip_until_newline = False
                        if line.strip():
                            new_lines.append(line)
                else:
                    new_lines.append(line)
            
            # Write back
            with open(env_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(new_lines))
                if not new_lines[-1].endswith('\n'):
                    f.write('\n')
            
            print("✅ Updated .env file with correct API key")
    else:
        print("⚠️  No OPENAI_API_KEY found, adding it...")
        with open(env_file, 'a', encoding='utf-8') as f:
            f.write(f"\nOPENAI_API_KEY={WORKING_KEY}\n")
            if "OPENAI_MODEL" not in content:
                f.write("OPENAI_MODEL=gpt-3.5-turbo\n")
        print("✅ Added API key to .env file")

print("\n" + "=" * 60)
print("Done! Please restart your server for changes to take effect.")

