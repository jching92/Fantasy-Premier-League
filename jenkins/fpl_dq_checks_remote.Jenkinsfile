// fpl_dq_checks_remote
// Clones jching92/Fantasy-Premier-League, runs dq_checks.py for the chosen
// season(s) and fails the build if any check fails. Publishes one JUnit
// report per season/gameweek (season<S>_gw<NN>).
//
// Job setup: Pipeline script from SCM -> Git -> this repo,
//            Script Path: jenkins/fpl_dq_checks_remote.Jenkinsfile
// Triggered downstream by fpl_gw_generator, or run manually.

pipeline {
    agent any
    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '50'))
    }
    // Optional: also check whenever the remote branch changes
    // triggers { pollSCM('H/30 * * * *') }
    parameters {
        string(name: 'BRANCH', defaultValue: 'master',
               description: 'Branch of Fantasy-Premier-League to check')
        string(name: 'SEASONS', defaultValue: '2026-27',
               description: 'Season folder(s) under data/, separated by spaces or commas')
        string(name: 'EXPECTED_GW', defaultValue: '',
               description: 'Optional: latest GW that must exist (fails if missing). Blank = highest GW found')
    }
    environment {
        // Dynamically sets path based on the user executing the Jenkins agent
        VENV_PATH   = "/home/${env.USER}/venv/313venv"
        RESULTS_DIR = 'fpl_dq_junit_results'
    }
    stages {
        stage('Checkout Source') {
            steps {
                script {
                    def seasons = params.SEASONS.trim().split(/[\s,]+/) as List
                    def sparse  = ['/*.py', '/requirements*.txt'] + seasons.collect { "/data/${it}/gws/" }
                    checkout([
                        $class: 'GitSCM',
                        branches: [[name: "*/${params.BRANCH}"]],
                        // Same URL and credentials as selected in the job UI
                        userRemoteConfigs: scm.userRemoteConfigs,
                        extensions: [
                            [$class: 'CleanBeforeCheckout'],
                            [$class: 'CloneOption', shallow: true, depth: 1, noTags: true, timeout: 20],
                            [$class: 'SparseCheckoutPaths',
                             sparseCheckoutPaths: sparse.collect { [$class: 'SparseCheckoutPath', path: it] }],
                        ],
                    ])
                }
                sh 'git log -1 --format="Checking commit %h (%ci): %s"'
            }
        }
        stage('Setup Environment') {
            steps {
                echo "Checking and preparing Python virtual environment..."
                sh '''
                    #!/bin/bash
                    echo "System Python version:"
                    python3 --version || echo "python3 command not found on host system"

                    # Test if the requested parent directory is writable. If not, use a safe fallback path.
                    PARENT_DIR="$(dirname "$VENV_PATH")"
                    if ! mkdir -p "$PARENT_DIR" 2>/dev/null; then
                        echo "WARNING: Permission denied for $PARENT_DIR. Falling back to an isolated workspace directory."
                        VENV_PATH="${WORKSPACE}/.venv_313"
                    fi
                    mkdir -p "$(dirname "$VENV_PATH")"

                    if [ ! -d "$VENV_PATH" ]; then
                        echo "Virtual environment not found. Creating it at $VENV_PATH..."
                        python3 -m venv "$VENV_PATH"
                    else
                        echo "Found existing virtual environment at $VENV_PATH."
                    fi

                    echo "$VENV_PATH" > "${WORKSPACE}/resolved_venv_path.txt"
                    echo "Target virtual environment path resolved and locked to: $VENV_PATH"
                    "$VENV_PATH/bin/python" --version

                    echo "Installing dependencies..."
                    "$VENV_PATH/bin/python" -m pip install --upgrade pip
                    "$VENV_PATH/bin/python" -m pip install -r requirements.txt
                '''
            }
        }
        stage('Run DQ Checks') {
            steps {
                sh '''
                    #!/bin/bash
                    VENV_PATH=$(cat "${WORKSPACE}/resolved_venv_path.txt") || { echo "ERROR: resolved_venv_path.txt missing!"; exit 1; }

                    # Never publish stale XML from an earlier build
                    rm -rf "$RESULTS_DIR"
                    mkdir -p "$RESULTS_DIR"

                    GW_ARG=""
                    if [ -n "$EXPECTED_GW" ]; then GW_ARG="--gw $EXPECTED_GW"; fi

                    STATUS=0
                    for SEASON in $(echo "$SEASONS" | tr ',' ' '); do
                        echo "=== dq_checks.py for $SEASON ==="
                        if [ ! -d "data/$SEASON/gws" ]; then
                            echo "ERROR: data/$SEASON/gws not found on $BRANCH"
                            STATUS=1
                            continue
                        fi
                        "$VENV_PATH/bin/python" dq_checks.py "data/$SEASON/gws" \
                            --season "$SEASON" $GW_ARG \
                            --junit-dir "$RESULTS_DIR/$SEASON" \
                            -o "$RESULTS_DIR/$SEASON/duplicates.csv" || STATUS=1
                    done
                    exit $STATUS
                '''
            }
        }
    }
    post {
        always {
            junit allowEmptyResults: true, testResults: "${env.RESULTS_DIR}/**/*.xml"
            archiveArtifacts allowEmptyArchive: true, artifacts: "${env.RESULTS_DIR}/**/duplicates.csv"
            sh "rm -f ${WORKSPACE}/resolved_venv_path.txt"
        }
    }
}
