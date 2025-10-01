#!/usr/bin/env python3
"""
Comprehensive Test Runner

Runs all tests and provides a clear summary.
Can be run with a background server or will start one temporarily.

Usage:
    # Run all tests (starts temporary server)
    python scripts/run_tests.py

    # Run specific test file
    python scripts/run_tests.py tests/test_skill_system.py

    # Run with existing server (faster)
    python scripts/run_tests.py --use-existing-server

    # Verbose output
    python scripts/run_tests.py -v
"""

import sys
import os
import subprocess
import time
import signal
import requests
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class Colors:
    """ANSI color codes"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class TestRunner:
    def __init__(self, use_existing_server=False, verbose=False):
        self.use_existing_server = use_existing_server
        self.verbose = verbose
        self.server_process = None
        self.server_port = 8000

    def check_server_running(self):
        """Check if server is already running"""
        try:
            response = requests.get(f"http://localhost:{self.server_port}/health", timeout=2)
            return response.status_code == 200
        except:
            return False

    def start_server(self):
        """Start FastAPI server in background"""
        print(f"\n{Colors.OKCYAN}Starting test server...{Colors.ENDC}")

        # Start server
        self.server_process = subprocess.Popen(
            ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(self.server_port)],
            stdout=subprocess.PIPE if not self.verbose else None,
            stderr=subprocess.PIPE if not self.verbose else None,
            cwd=project_root
        )

        # Wait for server to be ready
        max_wait = 10
        for i in range(max_wait):
            if self.check_server_running():
                print(f"{Colors.OKGREEN}✓ Server started successfully{Colors.ENDC}")
                return True
            time.sleep(1)
            print(f"  Waiting for server... ({i+1}/{max_wait})")

        print(f"{Colors.FAIL}✗ Server failed to start{Colors.ENDC}")
        return False

    def stop_server(self):
        """Stop the test server"""
        if self.server_process:
            print(f"\n{Colors.OKCYAN}Stopping test server...{Colors.ENDC}")
            self.server_process.send_signal(signal.SIGTERM)
            self.server_process.wait(timeout=5)
            print(f"{Colors.OKGREEN}✓ Server stopped{Colors.ENDC}")

    def run_pytest(self, test_files=None):
        """Run pytest with specified files or all tests"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}Running Tests{Colors.ENDC}")
        print("=" * 60)

        # Build pytest command
        cmd = ["pytest"]

        if test_files:
            cmd.extend(test_files)
        else:
            cmd.append("tests/")

        # Add options
        if self.verbose:
            cmd.append("-v")
        else:
            cmd.append("-q")

        cmd.extend([
            "--tb=short",  # Short traceback format
            "-ra",  # Show summary of all test outcomes
            "--color=yes"
        ])

        # Run pytest
        result = subprocess.run(cmd, cwd=project_root)
        return result.returncode == 0

    def run_health_checks(self):
        """Run basic health checks against the server"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}Health Checks{Colors.ENDC}")
        print("=" * 60)

        checks = [
            ("Server Health", f"http://localhost:{self.server_port}/health"),
            ("Root Endpoint", f"http://localhost:{self.server_port}/"),
            ("Skills List", f"http://localhost:{self.server_port}/api/v1/skills/list"),
            ("Env Check", f"http://localhost:{self.server_port}/debug/env-check"),
        ]

        all_passed = True
        for name, url in checks:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    print(f"{Colors.OKGREEN}✓{Colors.ENDC} {name}")
                else:
                    print(f"{Colors.FAIL}✗{Colors.ENDC} {name} (status: {response.status_code})")
                    all_passed = False
            except Exception as e:
                print(f"{Colors.FAIL}✗{Colors.ENDC} {name} (error: {e})")
                all_passed = False

        return all_passed

    def run(self, test_files=None):
        """Main test runner"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}VAPI Skills System - Test Suite{Colors.ENDC}")
        print("=" * 60)

        server_was_running = self.check_server_running()

        if server_was_running:
            print(f"{Colors.OKGREEN}✓ Using existing server at http://localhost:{self.server_port}{Colors.ENDC}")
        elif self.use_existing_server:
            print(f"{Colors.FAIL}✗ No server running at http://localhost:{self.server_port}{Colors.ENDC}")
            print(f"  Start server first or run without --use-existing-server")
            return False
        else:
            if not self.start_server():
                return False

        try:
            # Run health checks
            health_passed = self.run_health_checks()

            # Run pytest
            tests_passed = self.run_pytest(test_files)

            # Summary
            print(f"\n{Colors.HEADER}{Colors.BOLD}Test Summary{Colors.ENDC}")
            print("=" * 60)

            if health_passed and tests_passed:
                print(f"{Colors.OKGREEN}{Colors.BOLD}✓ ALL TESTS PASSED{Colors.ENDC}")
                return True
            else:
                print(f"{Colors.FAIL}{Colors.BOLD}✗ SOME TESTS FAILED{Colors.ENDC}")
                if not health_passed:
                    print(f"{Colors.FAIL}  - Health checks failed{Colors.ENDC}")
                if not tests_passed:
                    print(f"{Colors.FAIL}  - Unit/integration tests failed{Colors.ENDC}")
                return False

        finally:
            # Clean up
            if not server_was_running and not self.use_existing_server:
                self.stop_server()


def main():
    """Parse arguments and run tests"""
    import argparse

    parser = argparse.ArgumentParser(description="Run VAPI Skills System tests")
    parser.add_argument("test_files", nargs="*", help="Specific test files to run")
    parser.add_argument("--use-existing-server", action="store_true",
                        help="Use existing server instead of starting one")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose output")

    args = parser.parse_args()

    runner = TestRunner(
        use_existing_server=args.use_existing_server,
        verbose=args.verbose
    )

    success = runner.run(args.test_files)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
