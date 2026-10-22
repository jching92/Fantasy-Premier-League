// fpl_gw_generator
// Generates a new gameweek with update_gw.py, gates it on dq_checks.py, pushes
// the data to the remote branch only if every check passes, then triggers
// fpl_dq_checks_remote against what was pushed.
//
// Job setup: a plain Pipeline job (not Multibranch: its own push to the branch
//            would trigger it again with no GW). Pipeline script from SCM ->
//            Git -> this repo, with credentials that can push.
//            Script Path: jenkins/fpl_gw_generator.Jenkinsfile
//
// Note: the FPL API only serves the current season. update_gw.py refuses to
// run if SEASON doesn't match what the API is serving.

pipeline {
    agent any
    options {
        // The default checkout is a full, non-sparse clone; ours is shallow + sparse
        skipDefaultCheckout()
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
        string(name: 'DQ_JOB', defaultValue: 'fpl_dq_checks_remote',
               description: 'Downstream DQ job to trigger after a push, e.g. fpl_dq_checks_github/master for a Multibranch job. Blank = none')
    }
    environment {
        // Outside the workspace so the clean checkout doesn't delete it each build
        VENV_PATH   = "${env.HOME}/venv/313venv"
        RESULTS_DIR = 'fpl_dq_junit_results'
        // Copied from params explicitly: on a job's first build Jenkins doesn't
        // export parameters to sh steps yet, so $GEN_SEASON/$GEN_GW would be empty.
        GEN_SEASON           = "${params.SEASON?.trim() ?: '2026-27'}"
        GEN_GW               = "${params.GW?.trim() ?: ''}"
        GEN_BRANCH           = "${params.BRANCH?.trim() ?: 'master'}"
        GEN_REQUIRE_FINISHED = "${params.REQUIRE_FINISHED == null ? true : params.REQUIRE_FINISHED}"
    }
    stages {
        stage('Validate Parameters') {
            steps {
                script {
                    if (!(env.GEN_GW ==~ /\d+/) || env.GEN_GW.toInteger() < 1) {
                        error("GW must be a positive integer, got '${env.GEN_GW}'. Use Build with Parameters.")
                    }
                    if (!(env.GEN_SEASON ==~ /\d{4}-\d{2}/)) {
                        error("SEASON must look like 2026-27, got '${env.GEN_SEASON}'")
                    }
                    currentBuild.displayName = "#${env.BUILD_NUMBER} ${env.GEN_SEASON} GW${env.GEN_GW}"
                }
            }
        }
        stage('Checkout Source') {
            steps {
                script {
                    checkout([
                        $class: 'GitSCM',
                        branches: [[name: "*/${env.GEN_BRANCH}"]],
                        userRemoteConfigs: scm.userRemoteConfigs,
                        extensions: [
                            // Drop untracked output from earlier failed runs
                            [$class: 'CleanBeforeCheckout'],
                            [$class: 'CloneOption', shallow: true, depth: 1, noTags: true, timeout: 20],
                            // Only the scripts and this season's data
                            [$class: 'SparseCheckoutPaths', sparseCheckoutPaths: [
                                [$class: 'SparseCheckoutPath', path: '/*.py'],
                                [$class: 'SparseCheckoutPath', path: '/requirements.txt'],
                                [$class: 'SparseCheckoutPath', path: "/data/${env.GEN_SEASON}/"],
                            ]],
                            // Check out onto a real branch (not detached HEAD) so we can commit
                            [$class: 'LocalBranch', localBranch: env.GEN_BRANCH],
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
                    "$VENV_PATH/bin/python" -m pip install -r requirements.txt
                '''
            }
        }
        stage('Generate GW') {
            steps {
                sh '''
                    #!/bin/bash
                    VENV_PATH=$(cat "${WORKSPACE}/resolved_venv_path.txt") || exit 1
                    FINISHED_ARG=""
                    if [ "$GEN_REQUIRE_FINISHED" = "true" ]; then FINISHED_ARG="--require-finished"; fi
                    "$VENV_PATH/bin/python" update_gw.py "$GEN_GW" --season "$GEN_SEASON" $FINISHED_ARG
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
                    mkdir -p "$RESULTS_DIR/$GEN_SEASON"
                    "$VENV_PATH/bin/python" dq_checks.py "data/$GEN_SEASON/gws" \
                        --season "$GEN_SEASON" --gw "$GEN_GW" \
                        --junit-dir "$RESULTS_DIR/$GEN_SEASON" \
                        -o "$RESULTS_DIR/$GEN_SEASON/duplicates.csv"
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
                            git add -A "data/$GEN_SEASON"
                            if git diff --cached --quiet; then
                                echo "No data changes for $GEN_SEASON GW$GEN_GW; nothing to push."
                                echo "nothing" > "${WORKSPACE}/push_result.txt"
                                exit 0
                            fi
                            git diff --cached --stat | tail -5
                            git -c user.name="Jenkins (fpl_gw_generator)" \
                                -c user.email="jenkins@jching-rpi4" \
                                commit -q -m "GW$GEN_GW $GEN_SEASON (fpl_gw_generator #$BUILD_NUMBER)"
                            # Rejected if the branch moved since checkout; re-run the job in that case
                            git push origin "HEAD:refs/heads/$GEN_BRANCH" || {
                                echo "ERROR: push rejected ($GEN_BRANCH changed since checkout?). Re-run the job."
                                exit 1
                            }
                            git log -1 --format="Pushed %h to $GEN_BRANCH"
                            echo "pushed" > "${WORKSPACE}/push_result.txt"
                        '''
                    }
                }
            }
        }
        stage('Trigger DQ job') {
            when {
                allOf {
                    expression { params.PUSH }
                    expression { params.DQ_JOB?.trim() }
                    expression { fileExists('push_result.txt') && readFile('push_result.txt').trim() == 'pushed' }
                }
            }
            steps {
                build job: params.DQ_JOB.trim(), wait: false, parameters: [
                    string(name: 'BRANCH', value: env.GEN_BRANCH),
                    string(name: 'SEASONS', value: env.GEN_SEASON),
                    string(name: 'EXPECTED_GW', value: env.GEN_GW),
                ]
            }
        }
    }
    post {
        always {
            junit allowEmptyResults: true, testResults: "${env.RESULTS_DIR}/**/*.xml"
            archiveArtifacts allowEmptyArchive: true, artifacts: [
                "data/${env.GEN_SEASON}/gws/gw${env.GEN_GW}.csv",
                "data/${env.GEN_SEASON}/gws/xP${env.GEN_GW}.csv",
                "${env.RESULTS_DIR}/**/duplicates.csv",
            ].join(', ')
            sh "rm -f ${WORKSPACE}/resolved_venv_path.txt ${WORKSPACE}/push_result.txt"
        }
    }
}
