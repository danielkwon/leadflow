#!/usr/bin/env bash
# =========================================================================
#  LeadFlow SaaS 배포 자동화 스크립트 (CI/CD & 무중단 자동 롤백)
#
#  사용법:
#    ./deploy.sh              # 테스트 → DB 백업 → 이미지 빌드 → 배포
#    ./deploy.sh --skip-tests # 테스트 없이 바로 이미지 빌드 및 배포
#    ./deploy.sh --build-only # Docker 이미지만 빌드 (배포 안 함)
#    ./deploy.sh --rollback   # 이전 정상 이미지 버전으로 즉각 롤백
# =========================================================================
set -euo pipefail

# --- 기본 디렉토리 설정 ---
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"
SERVICES=("leadflow-web" "leadflow-scheduler" "leadflow-monitor")
LOG_FILE="${PROJECT_DIR}/data/deploy.log"
BACKUP_TAG="rollback"
DB_DIR="${PROJECT_DIR}/data"
DB_BACKUP_DIR="${DB_DIR}/backups"

# --- 색상 설정 (터미널 뷰어 보조) ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# --- 유틸리티 로그 출력 헬퍼 ---
log()   { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }
ok()    { echo -e "${GREEN}✅ $*${NC}"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ $*" >> "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ $*" >> "$LOG_FILE"; }
fail()  { echo -e "${RED}❌ $*${NC}"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ $*" >> "$LOG_FILE"; exit 1; }

mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$DB_BACKUP_DIR"

# --- 인자 파싱 ---
SKIP_TESTS=false
BUILD_ONLY=false
ROLLBACK=false

for arg in "$@"; do
    case "$arg" in
        --skip-tests) SKIP_TESTS=true ;;
        --build-only) BUILD_ONLY=true ;;
        --rollback)   ROLLBACK=true ;;
        --help|-h)
            echo "사용법: $0 [--skip-tests] [--build-only] [--rollback]"
            exit 0
            ;;
        *) warn "알 수 없는 옵션: $arg" ;;
    esac
done

# =========================================================================
#  Phase 0: 수동 롤백 (Rollback Routine)
# =========================================================================
if [ "$ROLLBACK" = true ]; then
    log "🔄 Phase 0: 이전 정상 구동 버전 이미지 롤백 시작"

    for svc in "${SERVICES[@]}"; do
        image_name="leadflow-${svc}"
        if docker image inspect "${image_name}:${BACKUP_TAG}" &>/dev/null; then
            docker tag "${image_name}:${BACKUP_TAG}" "${image_name}:latest"
            ok "${svc} 이미지를 직전 백업 버전(:${BACKUP_TAG})으로 복원 완료"
        else
            fail "${svc}의 rollback 백업 이미지가 존재하지 않습니다. 배포 이력이 필요합니다."
        fi
    done

    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" up -d --no-build
    ok "롤백 복구 완료 — 서비스가 안정적으로 이전 버전으로 재구동되었습니다."
    exit 0
fi

# =========================================================================
#  Phase 1: Pre-flight 환경 및 상태 점검
# =========================================================================
log "🔍 Phase 1: Pre-flight 상태 점검"

cd "$PROJECT_DIR"
if ! git diff --quiet HEAD 2>/dev/null; then
    warn "커밋되지 않은 로컬 작업 파일이 감지되었습니다."
    git status --short
    echo ""
    read -r -p "$(echo -e "${YELLOW}무시하고 배포를 계속 진행할까요? (y/N): ${NC}")" confirm
    if [[ "$confirm" != [yY] ]]; then
        fail "배포 중단: 먼저 변경사항을 git commit 하십시오."
    fi
fi

GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
log "  Git Branch/Hash: ${GIT_BRANCH}@${GIT_HASH}"

if ! docker info &>/dev/null; then
    fail "Docker 데몬이 구동 중이지 않습니다. Docker를 실행해 주세요."
fi
ok "Pre-flight 점검 통과"

# =========================================================================
#  Phase 2: 데이터베이스 스냅샷 백업
# =========================================================================
log "💾 Phase 2: SQLite 데이터베이스 스냅샷 백업"

BACKUP_TS=$(date '+%Y%m%d_%H%M%S')
for db_file in "$DB_DIR"/*.db; do
    if [ -f "$db_file" ]; then
        db_name=$(basename "$db_file")
        backup_file="${DB_BACKUP_DIR}/${db_name}_${BACKUP_TS}"
        cp "$db_file" "$backup_file"
        ok "DB 백업 완료: ${db_name} → $(basename "$backup_file")"

        # 7일 이상 지난 백업은 자동 정리
        find "$DB_BACKUP_DIR" -name "${db_name}_*" -mtime +7 -delete 2>/dev/null || true
    fi
done
log "  백업 경로: ${DB_BACKUP_DIR}"

# =========================================================================
#  Phase 3: 테스트 실행 (공통 패키지 + 두 모듈)
# =========================================================================
if [ "$SKIP_TESTS" = false ]; then
    log "🧪 Phase 3: 통합 테스트 자동 구동"

    # leadflow_common 패키지 테스트
    if [ -f "${PROJECT_DIR}/leadflow_common/.venv/bin/pytest" ]; then
        log "공통 패키지 테스트 중..."
        TEST_OUTPUT=$(cd "${PROJECT_DIR}/leadflow_common" && .venv/bin/pytest -v 2>&1) || {
            echo "$TEST_OUTPUT"
            fail "공통 패키지 통합 테스트 실패 — 배포가 거부되었습니다."
        }
        ok "공통 패키지 테스트 통과"
    else
        warn "leadflow_common 가상환경 pytest 미발견 — pip install -e .[dev] 실행 후 재시도"
    fi

    # leadflow 패키지 테스트
    if [ -f "${PROJECT_DIR}/leadflow/.venv/bin/pytest" ]; then
        log "leadflow Web 패키지 테스트 중..."
        TEST_OUTPUT=$(cd "${PROJECT_DIR}/leadflow" && .venv/bin/pytest -v 2>&1) || {
            echo "$TEST_OUTPUT"
            fail "leadflow 통합 테스트 실패 — 배포가 거부되었습니다."
        }
        PASSED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ passed' | head -1 || echo "테스트 통과")
        ok "leadflow 테스트 성공: ${PASSED}"
    fi

    # sales_pipeline 패키지 테스트
    if [ -f "${PROJECT_DIR}/sales_pipeline/.venv/bin/pytest" ]; then
        log "sales_pipeline Worker 패키지 테스트 중..."
        TEST_OUTPUT=$(cd "${PROJECT_DIR}/sales_pipeline" && .venv/bin/pytest -v 2>&1) || {
            echo "$TEST_OUTPUT"
            fail "sales_pipeline 통합 테스트 실패 — 배포가 거부되었습니다."
        }
        PASSED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ passed' | head -1 || echo "테스트 통과")
        ok "sales_pipeline 테스트 성공: ${PASSED}"
    fi
else
    warn "Phase 3: 통합 테스트 건너뜀 (--skip-tests 적용됨)"
fi

# =========================================================================
#  Phase 4: 빌드 및 이전 이미지 백업
# =========================================================================
log "🏗️  Phase 4: Docker 멀티스테이지 이미지 빌드 개시"

# 현재 running 이미지들을 rollback 태그로 사전 이중 백업
for svc in "${SERVICES[@]}"; do
    image_name="leadflow-${svc}"
    if docker image inspect "${image_name}:latest" &>/dev/null; then
        docker tag "${image_name}:latest" "${image_name}:${BACKUP_TAG}"
        log "  ${svc}: 기존 최신 이미지를 :${BACKUP_TAG} 로 백업 보관"
    fi
done

# Compose 빌드 수행
cd "$PROJECT_DIR"
log "Docker Compose 무캐시(--no-cache) 빌드 중..."
BUILD_OUTPUT=$(docker compose -f "$COMPOSE_FILE" build --no-cache 2>&1) || {
    echo "$BUILD_OUTPUT"
    fail "Docker 이미지 빌드 실패"
}
ok "새 이미지 빌드 완수 (${GIT_BRANCH}@${GIT_HASH})"

if [ "$BUILD_ONLY" = true ]; then
    ok "빌드 전용 모드 완료 — 원격 배포 단계는 건너뜁니다."
    exit 0
fi

# =========================================================================
#  Phase 5: 무중단 컨테이너 기동
# =========================================================================
log "🚀 Phase 5: 컨테이너 업그레이드 배포 실행"

cd "$PROJECT_DIR"
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans 2>&1 || {
    warn "컨테이너 기동 오류 감지 — 직전 정상 버전으로 자동 롤백을 작동합니다..."
    "$0" --rollback
    fail "기동 에러로 배포 실패 후 자동 롤백 완료. 디테일 로그를 점검하세요: ${LOG_FILE}"
}

# =========================================================================
#  Phase 6: HTTP Health Check 및 정합성 검증
# =========================================================================
log "💓 Phase 6: 실시간 HTTP Health Check 개시"

HEALTH_OK=false
MAX_RETRIES=15
RETRY_INTERVAL=3

for i in $(seq 1 $MAX_RETRIES); do
    sleep $RETRY_INTERVAL

    ALL_RUNNING=true
    for svc in "${SERVICES[@]}"; do
        STATUS=$(docker inspect --format='{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
        if [ "$STATUS" != "running" ]; then
            ALL_RUNNING=false
            break
        fi
    done

    if [ "$ALL_RUNNING" = true ]; then
        # 1차: 로그인 페이지 응답 확인
        HTTP_CODE=$(docker exec leadflow-web curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://localhost:8080/login" 2>/dev/null || echo "000")

        # 2차: 정적 자산 접근 확인 (CSS)
        STATIC_CODE=$(docker exec leadflow-web curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://localhost:8080/static/css/index.css" 2>/dev/null || echo "000")

        if [ "$HTTP_CODE" = "200" ] && [ "$STATIC_CODE" = "200" ]; then
            ok "Health Check 최종 통과! (시도: ${i}/${MAX_RETRIES}, 로그인: ${HTTP_CODE}, 정적파일: ${STATIC_CODE})"
            HEALTH_OK=true
            break
        elif [ "$HTTP_CODE" = "200" ]; then
            ok "Health Check 통과! (시도: ${i}/${MAX_RETRIES}, 로그인: ${HTTP_CODE})"
            HEALTH_OK=true
            break
        fi
    fi

    log "  Health Check 재검사 시도 ${i}/${MAX_RETRIES}..."
done

if [ "$HEALTH_OK" = false ]; then
    warn "Health Check 검사 최종 통과 실패 — 자동 즉각 롤백을 개시합니다..."

    for svc in "${SERVICES[@]}"; do
        log "  --- [장애] ${svc} 최근 20라인 에러 로그 ---"
        docker logs --tail 20 "$svc" 2>&1 >> "$LOG_FILE" || true
    done

    "$0" --rollback
    fail "서비스 건강 이상으로 배포 취소 및 자동 롤백 완료. 상세 장애 원인을 로그에서 확인하세요: ${LOG_FILE}"
fi

# =========================================================================
#  Phase 7: 배포 완료 결과 브리핑
# =========================================================================
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🎉 LeadFlow SaaS 플랫폼 무중단 배포 성공!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
log "배포 성공 완수: ${GIT_BRANCH}@${GIT_HASH} → $(date '+%Y-%m-%d %H:%M:%S')"

for svc in "${SERVICES[@]}"; do
    STATUS=$(docker inspect --format='{{.State.Status}}' "$svc" 2>/dev/null || echo "unknown")
    UPTIME=$(docker inspect --format='{{.State.StartedAt}}' "$svc" 2>/dev/null | cut -d'T' -f2 | cut -d'.' -f1 || echo "?")
    echo -e "  ${GREEN}●${NC} ${svc}: ${STATUS} (기동 시각: ${UPTIME})"
done

echo ""
echo -e "  📋 배포 이력 로그: ${LOG_FILE}"
echo -e "  💾 DB 백업 경로: ${DB_BACKUP_DIR}"
echo -e "  🔄 수동 롤백 복원: ${YELLOW}./deploy.sh --rollback${NC}"
echo ""
