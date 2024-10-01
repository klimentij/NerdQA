import subprocess
import sys
import os
from typing import List
from backend.src.benchmark.config import load_config, BenchmarkConfig, Probe

def generate_configs(base_config: BenchmarkConfig) -> List[BenchmarkConfig]:
    configs = []
    for system in base_config.system.values if isinstance(base_config.system, Probe) else [base_config.system]:
        new_config = base_config.copy(deep=True)
        new_config.system = system
        configs.append(new_config)
    return configs

def run_probe(config: BenchmarkConfig):
    # Convert the config to a JSON string
    config_json = config.model_dump_json()
    
    # Construct the command to run the benchmark
    cmd = [
        sys.executable,  # Use the current Python interpreter
        "-m", "backend.src.benchmark.run",  # Run the benchmark module
        "--config", config_json  # Pass the config as a JSON string
    ]
    
    # Run the command as a subprocess
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
    return process

def print_output(process, system):
    for line in process.stdout:
        print(f"[{system}] {line}", end='')

def main():
    base_config = load_config()
    configs = generate_configs(base_config)
    
    processes = []
    for config in configs:
        process = run_probe(config)
        processes.append((process, config.system))
    
    # Use separate threads to print output from each process
    from threading import Thread
    threads = []
    for process, system in processes:
        thread = Thread(target=print_output, args=(process, system))
        thread.start()
        threads.append(thread)
    
    # Wait for all processes to complete
    for process, system in processes:
        process.wait()
        if process.returncode != 0:
            print(f"Error in subprocess for {system}: Process exited with code {process.returncode}")
    
    # Wait for all output threads to complete
    for thread in threads:
        thread.join()

if __name__ == "__main__":
    main()