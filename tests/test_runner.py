import subprocess
import os
import sys

def run_script(script_path):
    try:
        result = subprocess.run(['python3', script_path], capture_output=True, text=True, check=True)
        print(f"--- Running {os.path.basename(script_path)} ---")
        print(result.stdout)
        print(f"--- Finished {os.path.basename(script_path)} ---")
    except FileNotFoundError:
        print(f"Error: The script '{script_path}' was not found.")
    except subprocess.CalledProcessError as e:
        print(f"Error running script: {os.path.basename(script_path)}")
        print(f"Return code: {e.returncode}")
        print(f"Output:\n{e.stdout}")
        print(f"Error output:\n{e.stderr}")

def run_module(module_name):
    try:
        result = subprocess.run(['python3', '-m', module_name], capture_output=True, text=True, check=True)
        print(f"--- Running module {module_name} ---")
        print(result.stdout)
        print(f"--- Finished module {module_name} ---")
    except subprocess.CalledProcessError as e:
        print(f"Error running module: {module_name}")
        print(f"Return code: {e.returncode}")
        print(f"Output:\n{e.stdout}")
        print(f"Error output:\n{e.stderr}")

if __name__ == "__main__":
    # Get the directory of the current script
    current_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(current_dir, '..'))

    # Run example scripts
    example_scripts = [
        'discover_devices.py',
    ]
    for script_name in example_scripts:
        script_path = os.path.join(project_root, 'examples', script_name)
        run_script(script_path)
    
    # Run test modules
    test_modules = [
        'tests.api_test',
        'tests.minimal_api',
        'tests.test_channel_rotation',
    ]
    for module_name in test_modules:
        run_module(module_name)