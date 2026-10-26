// fpl_upstream_xg_compare
// Compares player xG (and player/club counts) per gameweek between this fork
// and its upstream, vaastav/Fantasy-Premier-League, for the chosen season(s).
// Archives, per season:
//   xg_compare_<season>_<YYYYMMDDHHMMSS SGT>.pdf        summary + one page per GW
//   xg_compare_<season>_gwN_<ts>.pdf                    one PDF per GW
//   xg_compare_<season>_summary_<ts>.csv, _mismatches_<ts>.csv
//
// Build result:
//   SUCCESS  every GW present in both repos matches (players, clubs, xG)
//   UNSTABLE differences found (FAIL_ON_DIFF=false) - see the bold rows in the PDF
//   FAILURE  differences found and FAIL_ON_DIFF=true, or a season/folder is missing
// A GW that only one repo has yet (e.g. vaastav not caught up) is reported in
// the PDF but is not a difference.
//
// Job setup: plain Pipeline job -> Pipeline script from SCM -> Git ->
//            https://github.com/jching92/Fantasy-Premier-League.git, Branch */master,
//            Script Path: jenkins/fpl_upstream_xg_compare.Jenkinsfile

pipeline {
    agent any
    options {
        // The default checkout is a full, non-sparse clone; ours is shallow + sparse
        skipDefaultCheckout()
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '20'))
    }
    parameters {
        string(name: 'SEASONS', defaultValue: '2026-27',
               description: 'Season folder(s) under data/, separated by spaces or commas, e.g. "2026-27" or "2024-25 2025-26 2026-27"')
        string(name: 'BRANCH', defaultValue: 'master',
               description: 'Branch of this fork to compare')
        string(name: 'UPSTREAM_REPO', defaultValue: 'https://github.com/vaastav/Fantasy-Premier-League.git',
               description: 'Upstream repository (public, no credentials)')
        string(name: 'UPSTREAM_BRANCH', defaultValue: 'master',
               description: 'Upstream branch')
        booleanParam(name: 'FAIL_ON_DIFF', defaultValue: false,
                     description: 'Fail the build (instead of UNSTABLE) when players, clubs or xG differ')
    }
    environment {
        VENV_PATH    = "${env.HOME}/venv/313venv"
        OUT_DIR      = 'xg_compare_output'
        UPSTREAM_DIR = 'upstream'
        // Copied from params explicitly: on a job's first build Jenkins does not
        // export parameters to sh steps yet.
        XC_SEASONS         = "${params.SEASONS?.trim() ?: '2026-27'}"
        XC_BRANCH          = "${params.BRANCH?.trim() ?: 'master'}"
        XC_UPSTREAM_REPO   = "${params.UPSTREAM_REPO?.trim() ?: 'https://github.com/vaastav/Fantasy-Premier-League.git'}"
        XC_UPSTREAM_BRANCH = "${params.UPSTREAM_BRANCH?.trim() ?: 'master'}"
        XC_FAIL_ON_DIFF    = "${params.FAIL_ON_DIFF == null ? false : params.FAIL_ON_DIFF}"
    }
    stages {
        stage('Validate Parameters') {
            steps {
                script {
                    def seasons = env.XC_SEASONS.split(/[\s,]+/).findAll { it } as List
                    if (!seasons) { error('SEASONS is empty') }
                    seasons.each { if (!(it ==~ /\d{4}-\d{2}/)) { error("Each season must look like 2026-27, got '${it}'") } }
                    currentBuild.displayName = "#${env.BUILD_NUMBER} ${seasons.join(' ')}"
                }
            }
        }
        stage('Checkout Fork') {
            steps {
                script {
                    def seasons = env.XC_SEASONS.split(/[\s,]+/).findAll { it } as List
                    def sparse  = ['/*.py', '/requirements.txt'] + seasons.collectMany {
                        ["/data/${it}/gws/merged_gw.csv", "/data/${it}/players_raw.csv"]
                    }
                    checkout([
                        $class: 'GitSCM',
                        branches: [[name: "*/${env.XC_BRANCH}"]],
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
                sh 'git log -1 --format="Fork $XC_BRANCH at %h (%ci): %s" | tee fork_ref.txt'
            }
        }
        stage('Clone Upstream') {
            steps {
                sh '''
                    #!/bin/bash
                    set -e
                    rm -rf "$UPSTREAM_DIR"
                    # Shallow, blob-less, sparse: only the files compared are downloaded
                    GIT_LFS_SKIP_SMUDGE=1 git clone --quiet --depth 1 --filter=blob:none --no-checkout \
                        --branch "$XC_UPSTREAM_BRANCH" "$XC_UPSTREAM_REPO" "$UPSTREAM_DIR"
                    PATHS=""
                    for SEASON in $(echo "$XC_SEASONS" | tr ',' ' '); do
                        PATHS="$PATHS /data/$SEASON/gws/merged_gw.csv /data/$SEASON/players_raw.csv"
                    done
                    git -C "$UPSTREAM_DIR" sparse-checkout set --no-cone $PATHS
                    git -C "$UPSTREAM_DIR" checkout --quiet
                    git -C "$UPSTREAM_DIR" log -1 --format="Upstream $XC_UPSTREAM_BRANCH at %h (%ci): %s" | tee upstream_ref.txt
                '''
            }
        }
        stage('Setup Environment') {
            steps {
                sh '''
                    #!/bin/bash
                    PARENT_DIR="$(dirname "$VENV_PATH")"
                    if ! mkdir -p "$PARENT_DIR" 2>/dev/null; then
                        echo "WARNING: Permission denied for $PARENT_DIR. Using a workspace venv."
                        VENV_PATH="${WORKSPACE}/.venv_313"
                    fi
                    if [ ! -d "$VENV_PATH" ]; then
                        echo "Creating virtual environment at $VENV_PATH..."
                        python3 -m venv "$VENV_PATH"
                    fi
                    echo "$VENV_PATH" > "${WORKSPACE}/resolved_venv_path.txt"
                    "$VENV_PATH/bin/python" --version
                    "$VENV_PATH/bin/python" -m pip install --quiet --upgrade pip
                    "$VENV_PATH/bin/python" -m pip install --quiet -r requirements.txt
                '''
            }
        }
        stage('Compare xG') {
            steps {
                script {
                    def status = sh(returnStatus: true, script: '''
                        #!/bin/bash
                        VENV_PATH=$(cat "${WORKSPACE}/resolved_venv_path.txt") || exit 1
                        rm -rf "$OUT_DIR" && mkdir -p "$OUT_DIR"
                        RUN_TS=$(TZ=Asia/Singapore date +%Y%m%d%H%M%S)   # time of this run, SGT
                        NOTE="$(cat upstream_ref.txt) | $(cat fork_ref.txt)"

                        STATUS=0      # 0 = all match, 2 = differences, 1 = error
                        for SEASON in $(echo "$XC_SEASONS" | tr ',' ' '); do
                            echo "=== xg_compare.py for $SEASON ==="
                            "$VENV_PATH/bin/python" xg_compare.py \
                                --season "$SEASON" --fork-dir . --upstream-dir "$UPSTREAM_DIR" \
                                --out "$OUT_DIR/$SEASON" --tag "_$RUN_TS" --note "$NOTE"
                            RC=$?
                            if [ $RC -eq 1 ]; then STATUS=1
                            elif [ $RC -eq 2 ] && [ $STATUS -eq 0 ]; then STATUS=2
                            elif [ $RC -ne 0 ] && [ $RC -ne 2 ]; then STATUS=1
                            fi
                        done
                        exit $STATUS
                    ''')
                    if (status == 1) {
                        error('xg_compare.py failed (missing season folder or error) - see the log')
                    } else if (status == 2) {
                        if (env.XC_FAIL_ON_DIFF == 'true') {
                            error('Fork and upstream differ - see the PDF summary page (bold rows)')
                        }
                        unstable('Fork and upstream differ - see the PDF summary page (bold rows)')
                    }
                }
            }
        }
    }
    post {
        always {
            archiveArtifacts allowEmptyArchive: true,
                             artifacts: "${env.OUT_DIR}/**/*.pdf, ${env.OUT_DIR}/**/*.csv"
            // Single quotes + "$WORKSPACE": the shell expands it, quoted, so a job
            // name with spaces or brackets (e.g. "FPL calibration checks (remote)") works
            sh 'rm -f "$WORKSPACE/resolved_venv_path.txt" "$WORKSPACE/fork_ref.txt" "$WORKSPACE/upstream_ref.txt"'
        }
    }
}
