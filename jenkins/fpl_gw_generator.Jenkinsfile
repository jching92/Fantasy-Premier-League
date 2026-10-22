// fpl_gw_generator
// Generates a new gameweek with update_gw.py, gates it on dq_checks.py, pushes
// the data to the remote branch only if every check passes, then triggers
// fpl_dq_checks_remote against what was pushed.
//
// Job setup: Pipeline script from SCM -> Git -> this repo (with credentials
//            that can push), Script Path: jenkins/fpl_gw_generator.Jenkinsfile
//
// Note: the FPL API only serves the current season. update_gw.py refuses to
// run if SEASON doesn't match what the API is serving.

pipeline {
    agent any
    options {
        timeout(time: 120, unit: 'MINUTES')   // ~700 player API calls on the Pi
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '50'))
    }
    parameters {
        string(name: 'SEASON', defaultValue: '2026-27',
               description: 'Season folder under data/ (must be the season the FPL API is serving)')
        string(name: 'GW', defaultValue: '',
               description: 'Gameweek to generate, e.g. 8')
        string(name: 'BRANCH', defaultValue: 'master',
               description: 'Branch to clone and push to')
        booleanParam(name: 'REQUIRE_FINISHED', defaultValue: true,
                     description: 'Fail if FPL has not marked the GW as finished')
        booleanParam(name: 'PUSH', defaultValue: true,
                     description: 'Untick for a dry run: generate + check, but do not push or trigger downstream')
        string(name: 'GIT_CREDENTIALS_ID', defaultValue: '',
               description: 'Jenkins credentials (username + GitHub token) for the push. Blank = the job\'s SCM credentials')
    }
    environment {
        VENV_PATH   = "/home/${env.USER}/venv/313venv"
        RESULTS_DIR = 'fpl_dq_junit_results'
    }
    stages {
        stage('Validate Parameters') {
            steps {
                script {
                    if (!(params.GW ==~ /\d+/) || params.GW.toInteger() < 1) {
                        error("GW must be a positive integer, got '${params.GW}'")
                    }
                    if (!(params.SEASON ==~ /\d{4}-\d{2}/)) {
                        error("SEASON must look like 2026-27, got '${params.SEASON}'")
                    }
                    currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.SEASON} GW${params.GW}"
                }
            }
        }
        stage('Checkout Source') {
            steps {
                script {
                    checkout([
                        $class: 'GitSCM',
                        branches: [[name: "*/${params.BRANCH}"]],
                        userRemoteConfigs: scm.userRemoteConfigs,
                        extensions: [
                            // Drop untracked output from earlier failed runs
                            [$class: 'CleanBeforeCheckout'],
                            [$class: 'CloneOption', shallow: true, depth: 1, noTags: true, timeout: 20],
                            // Only the scripts and this season's data
                            [$class: 'SparseCheckoutPaths', sparseCheckoutPaths: [
                                [$class: 'SparseCheckoutPath', path: '/*.py'],
                                [$class: 'SparseCheckoutPath', path: '/requirements*.txt'],
                                [$class: 'SparseCheckoutPath', path: "/data/${params.SEASON}/"],
                            ]],
                            // Check out onto a real branch (not detached HEAD) so we can commit
                            [$class: 'LocalBranch', localBranch: params.BRANCH],
                        ],
                    ])
                }
                sh 'git log -1 --format="Starting from %h (%ci): %s"'
            }
        }
        stage('Setup Environment') {
            steps {
                echo "Checking and preparing Python virtual environment..."
                sh '''
                    #!/bin/bash
                    echo "System Python version:"
                    python3 --version || echo "python3 command not found on host system"

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
                    "$VENV_PATH/bin/python" -m pip install -r requirements-ci.txt
                '''
            }
        }
        stage('Generate GW') {
            steps {
                sh '''
                    #!/bin/bash
                    VENV_PATH=$(cat "${WORKSPACE}/resolved_venv_path.txt") || exit 1
                    FINISHED_ARG=""
                    if [ "$REQUIRE_FINISHED" = "true" ]; then FINISHED_ARG="--require-finished"; fi
                    "$VENV_PATH/bin/python" update_gw.py "$GW" --season "$SEASON" $FINISHED_ARG
                '''
            }
        }
        stage('DQ Checks') {
            steps {
                // Any failure stops the build here, so nothing is pushed
                sh '''
                    #!/bin/bash
                    VENV_PATH=$(cat "${WORKSPACE}/resolved_venv_path.txt") || exit 1
                    rm -rf "$RESULTS_DIR"
                    mkdir -p "$RESULTS_DIR/$SEASON"
                    "$VENV_PATH/bin/python" dq_checks.py "data/$SEASON/gws" \
                        --season "$SEASON" --gw "$GW" \
                        --junit-dir "$RESULTS_DIR/$SEASON" \
                        -o "$RESULTS_DIR/$SEASON/duplicates.csv"
                '''
            }
        }
        stage('Commit & Push') {
            when { expression { params.PUSH } }
            steps {
                script {
                    def credsId = params.GIT_CREDENTIALS_ID?.trim() ?: scm.userRemoteConfigs[0].credentialsId
                    if (!credsId) {
                        error('No push credentials: set GIT_CREDENTIALS_ID or select credentials in the job\'s SCM config')
                    }
                    withCredentials([gitUsernamePassword(credentialsId: credsId, gitToolName: 'Default')]) {
                        sh '''
                            #!/bin/bash
                            git add -A "data/$SEASON"
                            if git diff --cached --quiet; then
                                echo "No data changes for $SEASON GW$GW; nothing to push."
                                echo "nothing" > "${WORKSPACE}/push_result.txt"
                                exit 0
                            fi
                            git diff --cached --stat | tail -5
                            git -c user.name="Jenkins (fpl_gw_generator)" \
                                -c user.email="jenkins@jching-rpi4" \
                                commit -q -m "GW$GW $SEASON (fpl_gw_generator #$BUILD_NUMBER)"
                            # Rejected if the branch moved since checkout; re-run the job in that case
                            git push origin "HEAD:refs/heads/$BRANCH" || {
                                echo "ERROR: push rejected ($BRANCH changed since checkout?). Re-run the job."
                                exit 1
                            }
                            git log -1 --format="Pushed %h to $BRANCH"
                            echo "pushed" > "${WORKSPACE}/push_result.txt"
                        '''
                    }
                }
            }
        }
        stage('Trigger fpl_dq_checks_remote') {
            when {
                allOf {
                    expression { params.PUSH }
                    expression { fileExists('push_result.txt') && readFile('push_result.txt').trim() == 'pushed' }
                }
            }
            steps {
                build job: 'fpl_dq_checks_remote', wait: false, parameters: [
                    string(name: 'BRANCH', value: params.BRANCH),
                    string(name: 'SEASONS', value: params.SEASON),
                    string(name: 'EXPECTED_GW', value: params.GW),
                ]
            }
        }
    }
    post {
        always {
            junit allowEmptyResults: true, testResults: "${env.RESULTS_DIR}/**/*.xml"
            archiveArtifacts allowEmptyArchive: true, artifacts: [
                "data/${params.SEASON}/gws/gw${params.GW}.csv",
                "data/${params.SEASON}/gws/xP${params.GW}.csv",
                "${env.RESULTS_DIR}/**/duplicates.csv",
            ].join(', ')
            sh "rm -f ${WORKSPACE}/resolved_venv_path.txt ${WORKSPACE}/push_result.txt"
        }
    }
}
