// fpl_dq_checks_remote
// Clones jching92/Fantasy-Premier-League, runs dq_checks.py for the chosen
// season(s) and fails the build if any check fails. Publishes one JUnit
// report per season/gameweek (season<S>_gw<NN>).
//
// Works as a Multibranch Pipeline (checks the branch being built, and runs
// on every push the branch source picks up) or as a plain Pipeline job
// (checks the BRANCH parameter). Script Path:
// jenkins/fpl_dq_checks_remote.Jenkinsfile

pipeline {
    agent any
    options {
        // The default checkout is a full, non-sparse clone; ours is shallow + sparse
        skipDefaultCheckout()
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '50'))
    }
    parameters {
        string(name: 'BRANCH', defaultValue: 'master',
               description: 'Branch to check (plain Pipeline jobs only; Multibranch builds use their own branch)')
        string(name: 'SEASONS', defaultValue: '2026-27',
               description: 'Season folder(s) under data/, separated by spaces or commas')
        string(name: 'EXPECTED_GW', defaultValue: '',
               description: 'Optional: latest GW that must exist (fails if missing). Blank = highest GW found')
    }
    environment {
        // Outside the workspace so the clean checkout doesn't delete it each build
        VENV_PATH   = "${env.HOME}/venv/313venv"
        RESULTS_DIR = 'fpl_dq_junit_results'
        // Copied from params explicitly: on a job's first build (and the first
        // build of each new branch) Jenkins doesn't export parameters to sh
        // steps yet, which left $SEASONS empty and checked nothing.
        DQ_BRANCH      = "${env.BRANCH_NAME ?: (params.BRANCH ?: 'master')}"
        DQ_SEASONS     = "${params.SEASONS?.trim() ?: '2026-27'}"
        DQ_EXPECTED_GW = "${params.EXPECTED_GW?.trim() ?: ''}"
    }
    stages {
        stage('Checkout Source') {
            steps {
                script {
                    def seasons = env.DQ_SEASONS.split(/[\s,]+/) as List
                    def sparse  = ['/*.py', '/requirements.txt'] + seasons.collect { "/data/${it}/gws/" }
                    checkout([
                        $class: 'GitSCM',
                        branches: [[name: "*/${env.DQ_BRANCH}"]],
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
                sh 'git log -1 --format="Checking $DQ_BRANCH at %h (%ci): %s | seasons: $DQ_SEASONS"'
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
                    if [ -n "$DQ_EXPECTED_GW" ]; then GW_ARG="--gw $DQ_EXPECTED_GW"; fi

                    STATUS=0
                    CHECKED=0
                    for SEASON in $(echo "$DQ_SEASONS" | tr ',' ' '); do
                        echo "=== dq_checks.py for $SEASON ==="
                        if [ ! -d "data/$SEASON/gws" ]; then
                            echo "ERROR: data/$SEASON/gws not found on $DQ_BRANCH"
                            STATUS=1
                            continue
                        fi
                        CHECKED=$((CHECKED + 1))
                        "$VENV_PATH/bin/python" dq_checks.py "data/$SEASON/gws" \
                            --season "$SEASON" $GW_ARG \
                            --junit-dir "$RESULTS_DIR/$SEASON" \
                            -o "$RESULTS_DIR/$SEASON/duplicates.csv" || STATUS=1
                    done

                    # A run that checked nothing must not pass
                    if [ "$CHECKED" -eq 0 ]; then
                        echo "ERROR: no seasons were checked (DQ_SEASONS='$DQ_SEASONS')"
                        exit 1
                    fi
                    exit $STATUS
                '''
            }
        }
    }
    post {
        always {
            junit allowEmptyResults: true, testResults: "${env.RESULTS_DIR}/**/*.xml"
            archiveArtifacts allowEmptyArchive: true, artifacts: "${env.RESULTS_DIR}/**/duplicates.csv"
            // Quoted: works whatever the job (and so the workspace folder) is named
            sh 'rm -f "$WORKSPACE/resolved_venv_path.txt"'
        }
    }
}
