class SecretAuctionApp {
    constructor() {
        this.roomCode = null;
        this.currentRole = null; // 'admin' or 'team1'~'team6'
        this.selectedLandIndex = null; 
        
        // Initial / Default Game State Template
        this.defaultState = {
            phase: 'setup', // 'setup' (admin selecting target), 'bidding' (students bidding), 'revealed' (show bids), 'selecting_land' (winner locks land), 'game_over'
            round: 1,
            teams: {
                team1: { name: '1조 (적색)', points: 100, landsCount: 0, color: 'team1' },
                team2: { name: '2조 (오렌지)', points: 100, landsCount: 0, color: 'team2' },
                team3: { name: '3조 (황색)', points: 100, landsCount: 0, color: 'team3' },
                team4: { name: '4조 (녹색)', points: 100, landsCount: 0, color: 'team4' },
                team5: { name: '5조 (청색)', points: 100, landsCount: 0, color: 'team5' },
                team6: { name: '6조 (자색)', points: 100, landsCount: 0, color: 'team6' }
            },
            bids: {}, // { teamKey: bidAmount }
            bingoBoard: Array(16).fill(null), // Array of size 16 containing teamKey or null
            currentWinner: null, // Team key that won the current round
            winningLand: null, 
            targetLand: null, // Target land currently NOT selected initially
            aiComment: "방이 준비되었습니다. 사회자는 이번 라운드에 경매를 진행할 대상 땅 번호를 아래의 선택기에서 선택한 뒤 '경매 시작' 버튼을 눌러 입찰을 개시해 주십시오."
        };

        this.state = null;
        this.eventSource = null;
        this.pollingInterval = null;
        this.initializedAdminRoom = false;
        
        this.initCommunication();
    }

    initCommunication() {
        this.updateStatusIndicator("서버 연결 완료 (방 미지정)", "var(--color-primary)");
    }

    // Room connection logic
    joinRoomByCode() {
        const inputCode = document.getElementById('input-room-code').value.trim().toUpperCase();
        if (inputCode.length !== 4 || isNaN(inputCode)) {
            alert('방 코드는 숫자 4자리여야 합니다. (예: 1234)');
            return;
        }

        this.connectToRoom(inputCode);
    }

    connectToRoom(code) {
        this.roomCode = code;
        this.updateStatusIndicator(`실시간 연결 중 (방: ${code})`, "var(--color-gold)");

        // Close previous SSE and polling interval if exists
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }

        // Initialize SSE Connection via ntfy.sh (standard port 443 HTTPS, bypasses school firewalls)
        const sseUrl = `https://ntfy.sh/secret-auction-room-${this.roomCode}/sse`;
        this.eventSource = new EventSource(sseUrl);

        this.eventSource.onopen = () => {
            this.updateStatusIndicator(`실시간 연결됨 (방: ${this.roomCode})`, "var(--team4)");
        };

        this.eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                // ntfy.sh wraps messages inside entry object
                if (data && data.message) {
                    const payload = JSON.parse(data.message);
                    this.handleNetworkMessage(payload);
                }
            } catch (e) {
                console.error("Error parsing SSE message:", e);
            }
        };

        this.eventSource.onerror = (err) => {
            console.warn("SSE connection interrupted, starting polling fallback...", err);
            this.updateStatusIndicator(`연결 불안정 (폴링 전환, 방: ${this.roomCode})`, "var(--color-accent)");
            
            // Activate polling fallback immediately if not running
            if (!this.pollingInterval) {
                this.startPollingFallback();
            }
        };

        // Initialize state for Admin
        if (this.currentRole === 'admin') {
            this.state = JSON.parse(JSON.stringify(this.defaultState));
        }

        // Load cached messages to sync up immediately
        this.loadInitialState();

        // Force UI transition immediately
        this.onRoomConnected();
    }

    async loadInitialState() {
        try {
            const response = await fetch(`https://ntfy.sh/secret-auction-room-${this.roomCode}/json?poll=1&since=12h`);
            if (!response.ok) return;
            const text = await response.text();
            const lines = text.trim().split('\n');
            let latestStatePayload = null;
            
            for (let i = lines.length - 1; i >= 0; i--) {
                if (!lines[i]) continue;
                try {
                    const entry = JSON.parse(lines[i]);
                    if (entry.message) {
                        const payload = JSON.parse(entry.message);
                        if (payload && payload.type === 'state_sync' && payload.state) {
                            latestStatePayload = payload;
                            break; // Get the most recent valid state
                        }
                    }
                } catch (err) {
                    // Skip parsing error for single line
                }
            }

            if (latestStatePayload) {
                this.handleNetworkMessage(latestStatePayload);
            } else {
                if (this.currentRole === 'admin') {
                    this.syncStateToNetwork();
                }
            }
        } catch (e) {
            console.error("Error loading initial state:", e);
        }
    }

    handleNetworkMessage(payload) {
        if (!payload || payload.type !== 'state_sync' || !payload.state) return;
        
        const incomingState = payload.state;
        const sender = payload.sender;

        if (this.currentRole === 'admin') {
            // Admin only merges bids submitted by students during the bidding phase
            if (sender !== 'admin' && this.state && this.state.phase === 'bidding') {
                let stateChanged = false;
                const newBids = { ...this.state.bids };
                
                if (incomingState.bids) {
                    Object.entries(incomingState.bids).forEach(([teamKey, bidVal]) => {
                        if (newBids[teamKey] !== bidVal) {
                            newBids[teamKey] = bidVal;
                            stateChanged = true;
                        }
                    });
                }

                if (stateChanged) {
                    this.state.bids = newBids;
                    this.syncStateToNetwork();
                    this.render();
                }
            }
        } else {
            // Students adopt the authoritative state from the admin
            this.state = incomingState;
            this.render();
        }
    }

    startPollingFallback() {
        if (this.pollingInterval) clearInterval(this.pollingInterval);
        
        this.pollingInterval = setInterval(async () => {
            try {
                const response = await fetch(`https://ntfy.sh/secret-auction-room-${this.roomCode}/json?poll=1&since=10s`);
                if (!response.ok) return;
                const text = await response.text();
                const lines = text.trim().split('\n');
                
                for (let i = lines.length - 1; i >= 0; i--) {
                    if (!lines[i]) continue;
                    try {
                        const entry = JSON.parse(lines[i]);
                        if (entry.message) {
                            const payload = JSON.parse(entry.message);
                            if (payload && payload.type === 'state_sync' && payload.sender !== this.currentRole) {
                                this.handleNetworkMessage(payload);
                                break;
                            }
                        }
                    } catch (e) {}
                }
            } catch (err) {
                console.error("Polling fetch failed:", err);
            }
        }, 3000);
    }

    syncStateToNetwork() {
        if (this.state && this.roomCode) {
            const payload = {
                type: 'state_sync',
                state: this.state,
                sender: this.currentRole || 'unknown'
            };

            fetch(`https://ntfy.sh/secret-auction-room-${this.roomCode}`, {
                method: 'POST',
                body: JSON.stringify(payload)
            }).catch(err => {
                console.error("Error syncing state to network:", err);
            });
        }
    }

    onRoomConnected() {
        this.updateStatusIndicator(`실시간 연결됨 (방: ${this.roomCode})`, "var(--team4)");
        
        // Update Gate Screen UI
        document.getElementById('room-code-input-area').style.display = 'none';
        document.getElementById('room-code-status-area').style.display = 'block';
        document.getElementById('active-room-code-display').innerText = this.roomCode;
        
        // Unlock selection options
        const mainOptions = document.getElementById('gate-main-options');
        mainOptions.style.pointerEvents = 'auto';
        mainOptions.style.opacity = '1';
        document.getElementById('gate-instruction-text').innerText = "방 연결 완료! 관리자 혹은 조를 선택하여 입장하세요.";
        document.getElementById('gate-instruction-text').style.color = "var(--color-primary)";

        this.render();
    }

    disconnectRoom() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
        this.roomCode = null;
        this.state = null;
        this.initializedAdminRoom = false;

        // Reset Gate UI
        document.getElementById('room-code-input-area').style.display = 'block';
        document.getElementById('room-code-status-area').style.display = 'none';
        document.getElementById('input-room-code').value = '';
        
        const mainOptions = document.getElementById('gate-main-options');
        mainOptions.style.pointerEvents = 'none';
        mainOptions.style.opacity = '0.3';
        document.getElementById('gate-instruction-text').innerText = "※ 먼저 방 번호를 입력하여 연결하거나, 위 사회자 버튼으로 방을 생성해 주세요.";
        document.getElementById('gate-instruction-text').style.color = "var(--color-accent)";
        
        this.updateStatusIndicator("서버 연결 완료 (방 미지정)", "var(--color-primary)");
    }

    updateStatusIndicator(text, color) {
        const badge = document.getElementById('connection-status');
        if (badge) {
            badge.innerText = text;
            badge.style.borderColor = color;
            badge.style.color = color;
            badge.style.background = `rgba(255, 255, 255, 0.02)`;
        }
    }

    // Role Selection
    selectRole(role) {
        // If entering as admin and no room is connected yet, auto create a room
        if (role === 'admin' && !this.roomCode) {
            const randomCode = Math.floor(1000 + Math.random() * 9000).toString(); // 1000~9999 random
            this.currentRole = role;
            this.connectToRoom(randomCode);
            document.getElementById('screen-gate').classList.remove('active');
            document.getElementById('screen-admin').classList.add('active');
            return;
        }

        if (!this.roomCode) {
            alert('먼저 사회자가 생성한 방 번호 4자리를 입력하고 입장해 주세요.');
            return;
        }

        this.currentRole = role;
        document.getElementById('screen-gate').classList.remove('active');
        
        if (role === 'admin') {
            // CRITICAL BUG FIX: If admin enters an already connected room, ensure state is initialized!
            if (!this.state) {
                this.state = JSON.parse(JSON.stringify(this.defaultState));
            }
            document.getElementById('screen-admin').classList.add('active');
            this.syncStateToNetwork();
        } else {
            document.getElementById('screen-team').classList.add('active');
            
            // Set client specific labels
            const teamInfo = (this.state && this.state.teams && this.state.teams[role]) ? this.state.teams[role] : this.defaultState.teams[role];
            document.getElementById('client-team-name').innerText = teamInfo.name;
            
            // Adjust input max boundary dynamically based on remaining points
            const inputBid = document.getElementById('input-bid-amount');
            inputBid.max = teamInfo.points;
            inputBid.value = '';
        }
        this.render();
    }

    exitToGate() {
        this.currentRole = null;
        document.getElementById('screen-admin').classList.remove('active');
        document.getElementById('screen-team').classList.remove('active');
        document.getElementById('screen-gate').classList.add('active');
    }


    // Database push wrappers
    pushStateUpdate(updates) {
        if (this.state && this.roomCode) {
            this.state = { ...this.state, ...updates };
            this.syncStateToNetwork();
            this.render();
        }
    }

    // Client Side actions
    setQuickBid(val) {
        if (!this.currentRole) return;
        const currentPoints = this.state.teams[this.currentRole].points;
        const inputBid = document.getElementById('input-bid-amount');
        
        if (val === 'all') {
            inputBid.value = currentPoints;
        } else {
            inputBid.value = Math.min(val, currentPoints);
        }
    }

    submitBid() {
        if (!this.currentRole || !this.state) return;
        const inputBid = document.getElementById('input-bid-amount');
        let bidVal = parseInt(inputBid.value, 10);
        
        if (isNaN(bidVal) || bidVal < 0) {
            alert('올바른 입찰 금액을 입력해 주세요.');
            return;
        }

        const currentPoints = this.state.teams[this.currentRole].points;
        if (bidVal > currentPoints) {
            alert('보유한 포인트를 초과하여 입찰할 수 없습니다.');
            return;
        }

        // Save bid to Firebase
        const newBids = { ...this.state.bids, [this.currentRole]: bidVal };
        this.pushStateUpdate({ bids: newBids });
    }

    cancelBidSubmit() {
        if (!this.currentRole || !this.state) return;
        const newBids = { ...this.state.bids };
        delete newBids[this.currentRole];
        this.pushStateUpdate({ bids: newBids });
    }

    // Admin Side actions
    startBidding() {
        if (!this.state || this.state.phase !== 'setup') return;
        if (!this.state.targetLand) {
            alert('먼저 경매를 진행할 대상 땅 번호를 선택해 주세요.');
            return;
        }

        this.pushStateUpdate({
            phase: 'bidding',
            bids: {},
            aiComment: `[경매 개시] 사회자가 이번 라운드 경매 대상 땅을 ${this.state.targetLand}번으로 선포했습니다! 각 모둠은 비밀 입찰을 진행해 주십시오.`
        });
    }

    revealBids() {
        if (!this.state || this.state.phase !== 'bidding') return;

        const bids = this.state.bids || {};
        const activeTeams = Object.keys(this.state.teams);
        
        // Finalize bids: teams that didn't submit are treated as bidding 0 points.
        const finalizedBids = {};
        activeTeams.forEach(teamKey => {
            finalizedBids[teamKey] = bids[teamKey] !== undefined ? bids[teamKey] : 0;
        });

        // Deduct points from ALL teams immediately
        const newTeams = { ...this.state.teams };
        activeTeams.forEach(teamKey => {
            newTeams[teamKey].points = Math.max(0, newTeams[teamKey].points - finalizedBids[teamKey]);
        });

        // Calculate Winner based on custom ties rules
        const bidPairs = Object.entries(finalizedBids).sort((a, b) => b[1] - a[1]);
        
        let winnerKey = null;
        let aiBriefing = "";

        const topBid = bidPairs[0][1];
        const topBidders = bidPairs.filter(pair => pair[1] === topBid);

        if (topBidders.length === 1) {
            winnerKey = topBidders[0][0];
            aiBriefing = `[낙찰 완료] ${newTeams[winnerKey].name}이(가) ${topBid}포인트로 최고 입찰하여 낙찰을 거머쥐었습니다! 타 조들의 견제가 무위로 돌아갑니다.`;
        } else {
            const uniqueBids = [...new Set(bidPairs.map(p => p[1]))].sort((a,b) => b-a);
            let foundSecondWinner = false;
            
            if (uniqueBids.length > 1) {
                const secondBid = uniqueBids[1];
                const secondBidders = bidPairs.filter(pair => pair[1] === secondBid);
                
                if (secondBidders.length === 1) {
                    winnerKey = secondBidders[0][0];
                    aiBriefing = `[동점 규정 적용] 최고 입찰가인 ${topBid}포인트가 동점으로 무효 처리되었습니다. 2순위인 ${secondBid}포인트를 제출한 ${newTeams[winnerKey].name}이(가) 어부지리로 낙찰되었습니다!`;
                    foundSecondWinner = true;
                }
            }
            
            if (!foundSecondWinner) {
                winnerKey = null;
                aiBriefing = `[낙찰 실패] 최고가 동점(${topBid}P)이 발생하고 다음 순위의 유효 낙찰자가 없어 이번 라운드는 아무도 낙찰받지 못했습니다! 소중한 포인트만 소멸되었습니다.`;
            }
        }

        const totalBids = Object.values(finalizedBids).reduce((acc, curr) => acc + curr, 0);
        if (winnerKey && topBid > 40) {
            aiBriefing += ` 특히 ${newTeams[winnerKey].name}의 과감한 베팅이 돋보였습니다.`;
        } else if (!winnerKey) {
            aiBriefing += ` 포인트 눈치 싸움이 격렬합니다. 자산을 소진하고도 땅을 얻지 못한 모둠들의 타격이 큽니다.`;
        }

        if (winnerKey) {
            this.pushStateUpdate({
                phase: 'selecting_land',
                bids: finalizedBids,
                teams: newTeams,
                currentWinner: winnerKey,
                aiComment: aiBriefing
            });
        } else {
            this.pushStateUpdate({
                phase: 'revealed',
                bids: finalizedBids,
                teams: newTeams,
                currentWinner: null,
                aiComment: aiBriefing
            });
        }
    }

    confirmLandSelection() {
        if (!this.state || this.state.phase !== 'selecting_land') return;

        const targetIndex = this.state.targetLand - 1;
        if (targetIndex < 0 || targetIndex >= 16 || this.state.bingoBoard[targetIndex] !== null) {
            alert('오류: 이미 점유되었거나 유효하지 않은 땅입니다.');
            return;
        }

        const newBoard = [...this.state.bingoBoard];
        newBoard[targetIndex] = this.state.currentWinner;

        // Recalculate lands count
        const newTeams = { ...this.state.teams };
        Object.keys(newTeams).forEach(teamKey => {
            newTeams[teamKey].landsCount = newBoard.filter(val => val === teamKey).length;
        });

        // Check for Bingo Win
        const winCheck = this.checkBingo(newBoard);
        let nextPhase = 'revealed';
        let aiSpeech = this.state.aiComment;
        
        if (winCheck.won) {
            nextPhase = 'game_over';
            const winnerName = newTeams[winCheck.winner].name;
            aiSpeech = `[게임 종료] 축하합니다! ${winnerName}이(가) ${winCheck.lineType} 라인 빙고를 가장 먼저 완성하여 최종 승리하였습니다!`;
        } else if (this.state.round >= 16) {
            nextPhase = 'game_over';
            let topTeam = null;
            let maxLands = -1;
            let isTie = false;
            
            Object.entries(newTeams).forEach(([key, data]) => {
                if (data.landsCount > maxLands) {
                    maxLands = data.landsCount;
                    topTeam = key;
                    isTie = false;
                } else if (data.landsCount === maxLands) {
                    isTie = true;
                }
            });

            if (isTie) {
                aiSpeech = `[게임 종료] 16라운드가 만료되었습니다. 최대 땅 점유 개수가 동점으로 확인되어 공동 승리가 선언됩니다!`;
            } else {
                aiSpeech = `[게임 종료] 16라운드가 만료되었습니다. 총 ${maxLands}개의 땅을 소유한 ${newTeams[topTeam].name}이(가) 최종 승리하였습니다!`;
            }
        } else {
            aiSpeech += ` ${newTeams[this.state.currentWinner].name}이(가) ${this.state.targetLand}번 땅을 무사히 영토에 편입했습니다. 다음 경매를 진행할 땅을 사회자가 선포해 주십시오.`;
        }

        this.pushStateUpdate({
            phase: nextPhase,
            bingoBoard: newBoard,
            teams: newTeams,
            aiComment: aiSpeech
        });
    }

    startNextRound() {
        if (!this.state || this.state.phase !== 'revealed') return;

        this.pushStateUpdate({
            phase: 'setup',
            round: this.state.round + 1,
            bids: {},
            currentWinner: null,
            targetLand: null, // Reset selected land for the next round
            aiComment: `[새 라운드 대기] 사회자는 다음 ${this.state.round + 1}라운드에 경매에 올릴 땅 번호를 다시 선택하고 '경매 시작' 버튼을 눌러 주십시오.`
        });
    }

    setTargetLand(landNum) {
        if (this.currentRole !== 'admin' || !this.state) return;
        // Target land can only be modified in setup phase
        if (this.state.phase !== 'setup') {
            alert('경매가 진행 중이거나 마감된 단계에서는 경매 대상 땅을 변경할 수 없습니다.');
            return;
        }

        const num = parseInt(landNum, 10);
        if (num >= 1 && num <= 16) {
            // Check if this land is already owned
            if (this.state.bingoBoard[num - 1] !== null) {
                alert('이미 다른 조가 점유한 땅입니다. 다른 번호를 선택해 주세요.');
                return;
            }

            this.pushStateUpdate({ 
                targetLand: num,
                aiComment: `사회자가 이번 라운드 경매 대상 땅을 ${num}번으로 임시 지정했습니다. '경매 시작' 버튼을 누르면 정식 경매가 게시됩니다.`
            });
        }
    }

    resetGame() {
        if (!this.state) return;
        if (confirm('모든 게임 상태를 초기화하시겠습니까?')) {
            const freshState = JSON.parse(JSON.stringify(this.defaultState));
            this.pushStateUpdate(freshState);
            alert('게임이 초기화되었습니다.');
        }
    }

    // Check Bingo lines 4x4
    checkBingo(board) {
        const lines = [
            // Rows
            [0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15],
            // Cols
            [0, 4, 8, 12], [1, 5, 9, 13], [2, 6, 10, 14], [3, 7, 11, 15],
            // Diagonals
            [0, 5, 10, 15], [3, 6, 9, 12]
        ];

        for (const line of lines) {
            const [a, b, c, d] = line;
            if (board[a] && board[a] === board[b] && board[a] === board[c] && board[a] === board[d]) {
                let lineType = "가로";
                if (a % 4 === 0 && b - a === 4) lineType = "세로";
                if (a === 0 && b === 5) lineType = "대각선";
                if (a === 3 && b === 6) lineType = "대각선";
                
                return { won: true, winner: board[a], lineType };
            }
        }
        return { won: false };
    }

    // UI RENDER ENGINE
    render() {
        if (!this.state) {
            // Defensive Fallback State to prevent UI crash when network state is loading
            this.state = JSON.parse(JSON.stringify(this.defaultState));
        }
        
        const { phase, round, teams, bids, bingoBoard, aiComment, targetLand } = this.state;
        const currentBids = bids || {};

        // --- 1. ADMIN PANEL RENDERING ---
        if (this.currentRole === 'admin') {
            document.getElementById('admin-round-num').innerText = round;
            document.getElementById('admin-room-badge').innerText = `ROOM: ${this.roomCode}`;
            
            const phaseMap = {
                'bidding': '실시간 모둠별 비밀 입찰 중...',
                'selecting_land': '낙찰 확인 대기 중',
                'revealed': '라운드 결과 확인 단계',
                'game_over': '게임 종료'
            };
            document.getElementById('game-phase-indicator').innerText = phaseMap[phase] || '설정 단계';

            const startBiddingBtn = document.getElementById('btn-start-bidding');
            const revealBtn = document.getElementById('btn-reveal-bids');
            const nextRoundBtn = document.getElementById('btn-next-round');
            
            const totalSubmitted = Object.keys(currentBids).length;
            document.getElementById('bid-status-summary').innerText = `제출 완료 (${totalSubmitted} / 6)`;

            if (phase === 'setup') {
                startBiddingBtn.style.display = 'block';
                startBiddingBtn.disabled = !targetLand;
                revealBtn.style.display = 'none';
                nextRoundBtn.style.display = 'none';
            } else if (phase === 'bidding') {
                startBiddingBtn.style.display = 'none';
                revealBtn.style.display = 'block';
                revealBtn.disabled = totalSubmitted === 0;
                nextRoundBtn.style.display = 'none';
            } else if (phase === 'revealed') {
                startBiddingBtn.style.display = 'none';
                revealBtn.style.display = 'none';
                nextRoundBtn.style.display = 'block';
            } else {
                startBiddingBtn.style.display = 'none';
                revealBtn.style.display = 'none';
                nextRoundBtn.style.display = 'none';
            }

            document.getElementById('admin-target-land-display').innerText = targetLand ? `${targetLand}번 땅` : '미지정';

            // Highlight target selector buttons
            const buttons = document.querySelectorAll('.target-land-selector-row button');
            buttons.forEach((btn, idx) => {
                if ((idx + 1) === targetLand) {
                    btn.style.background = 'var(--color-primary)';
                    btn.style.color = '#000';
                    btn.style.borderColor = 'var(--color-primary)';
                } else {
                    btn.style.background = 'transparent';
                    btn.style.color = 'var(--color-text)';
                    btn.style.borderColor = 'var(--border-color)';
                }
            });

            document.getElementById('ai-commentary').innerText = aiComment;

            const scoreboard = document.getElementById('admin-scoreboard');
            scoreboard.innerHTML = '';
            
            Object.entries(teams).forEach(([key, info]) => {
                const hasSubmitted = currentBids[key] !== undefined;
                const scoreRow = document.createElement('div');
                scoreRow.className = `score-row ${hasSubmitted ? 'submitted' : ''}`;
                
                let bidValText = '대기 중';
                if (phase === 'revealed' || phase === 'selecting_land' || phase === 'game_over') {
                    bidValText = `${currentBids[key] || 0} P`;
                } else if (hasSubmitted) {
                    bidValText = '제출 완료';
                }

                scoreRow.innerHTML = `
                    <div class="team-indicator">
                        <span class="color-dot ${info.color}"></span>
                        <span>${info.name}</span>
                    </div>
                    <div class="team-points-box">
                        <span class="team-bid-status">${bidValText}</span>
                        <span class="team-points">${info.points} P</span>
                    </div>
                `;
                scoreboard.appendChild(scoreRow);
            });

            const adminGrid = document.getElementById('admin-bingo-grid');
            adminGrid.innerHTML = '';
            
            bingoBoard.forEach((owner, idx) => {
                const cell = document.createElement('div');
                cell.className = `bingo-cell ${owner ? 'owned ' + owner : ''}`;
                if ((idx + 1) === targetLand && phase === 'bidding') {
                    cell.style.boxShadow = '0 0 15px var(--color-gold)';
                    cell.style.borderColor = 'var(--color-gold)';
                }
                
                let contentHtml = `<span class="cell-number">${idx + 1}</span>`;
                if (owner) {
                    contentHtml += `<span class="cell-owner">${teams[owner].name.split(' ')[0]}</span>`;
                }
                
                cell.innerHTML = contentHtml;
                adminGrid.appendChild(cell);
            });

            // Land Selection Modal (Confirm ownership of the targeted land)
            const modal = document.getElementById('land-selection-modal');
            if (phase === 'selecting_land' && this.state.currentWinner) {
                modal.classList.add('active');
                document.getElementById('modal-winner-badge').innerText = teams[this.state.currentWinner].name;
                document.getElementById('modal-winner-badge').className = `badge ${this.state.currentWinner}`;
                
                const modalGrid = document.getElementById('modal-bingo-grid');
                modalGrid.innerHTML = '';
                
                bingoBoard.forEach((owner, idx) => {
                    const cell = document.createElement('div');
                    const isTarget = (idx + 1) === targetLand;
                    cell.className = `modal-cell ${isTarget ? 'selected' : 'disabled'}`;
                    cell.innerText = idx + 1;
                    modalGrid.appendChild(cell);
                });
                
                document.getElementById('selected-land-number').innerText = `${targetLand}번 땅`;
                document.getElementById('btn-confirm-land').disabled = false;
            } else {
                modal.classList.remove('active');
            }
        }

        // --- 2. CLIENT (TEAM) PANEL RENDERING ---
        if (this.currentRole && this.currentRole.startsWith('team')) {
            const myTeamKey = this.currentRole;
            const myTeamInfo = teams[myTeamKey];
            
            document.getElementById('client-team-points').innerText = myTeamInfo.points;
            document.getElementById('client-team-lands').innerText = myTeamInfo.landsCount;
            
            const clientTargetLandNum = document.getElementById('client-target-land-num');
            if (clientTargetLandNum) {
                clientTargetLandNum.innerText = targetLand ? `${targetLand}번 땅` : '미지정';
            }
            
            const bidFormContainer = document.getElementById('bid-form-container');
            const bidCompleteContainer = document.getElementById('bid-complete-container');
            const submittedPreview = document.getElementById('submitted-amount-preview');
            
            const hasSubmitted = currentBids[myTeamKey] !== undefined;

            if (phase !== 'bidding') {
                bidFormContainer.style.display = 'none';
                bidCompleteContainer.style.display = 'block';
                
                const currentBidVal = currentBids[myTeamKey] !== undefined ? currentBids[myTeamKey] : 0;
                
                if (phase === 'setup') {
                    bidCompleteContainer.querySelector('h4').innerText = '경매 준비 중';
                    bidCompleteContainer.querySelector('p').innerText = '사회자가 이번 라운드에 경매할 땅을 임시 지정 중입니다. 잠시만 대기해 주세요.';
                    submittedPreview.innerText = '-';
                } else if (phase === 'revealed' || phase === 'selecting_land' || phase === 'game_over') {
                    bidCompleteContainer.querySelector('h4').innerText = '경매 라운드 종료';
                    bidCompleteContainer.querySelector('p').innerText = '결과가 공개되었습니다. 관리자의 다음 시작을 기다려 주세요.';
                    submittedPreview.innerText = currentBidVal;
                } else {
                    bidCompleteContainer.querySelector('h4').innerText = '입찰 대기 중';
                    bidCompleteContainer.querySelector('p').innerText = '사회자가 라운드를 시작할 때까지 대기해 주세요.';
                    submittedPreview.innerText = '-';
                }
                bidCompleteContainer.querySelector('.btn').style.display = 'none';
            } else {
                if (hasSubmitted) {
                    bidFormContainer.style.display = 'none';
                    bidCompleteContainer.style.display = 'block';
                    submittedPreview.innerText = currentBids[myTeamKey];
                    bidCompleteContainer.querySelector('h4').innerText = '입찰 완료';
                    bidCompleteContainer.querySelector('p').innerText = '사회자가 결과를 공개할 때까지 대기해 주세요.';
                    bidCompleteContainer.querySelector('.btn').style.display = 'inline-block';
                } else {
                    bidFormContainer.style.display = 'block';
                    bidCompleteContainer.style.display = 'none';
                    
                    const inputBid = document.getElementById('input-bid-amount');
                    inputBid.max = myTeamInfo.points;
                }
            }

            const clientGrid = document.getElementById('client-bingo-grid');
            clientGrid.innerHTML = '';
            
            bingoBoard.forEach((owner, idx) => {
                const cell = document.createElement('div');
                cell.className = `bingo-cell ${owner ? 'owned ' + owner : ''}`;
                if ((idx + 1) === targetLand && phase === 'bidding') {
                    cell.style.boxShadow = '0 0 10px var(--color-gold)';
                    cell.style.borderColor = 'var(--color-gold)';
                }
                
                let contentHtml = `<span class="cell-number">${idx + 1}</span>`;
                if (owner) {
                    contentHtml += `<span class="cell-owner">${teams[owner].name.split(' ')[0]}</span>`;
                }
                
                cell.innerHTML = contentHtml;
                clientGrid.appendChild(cell);
            });
        }
    }
}

// Instantiate App
const app = new SecretAuctionApp();
window.app = app;
