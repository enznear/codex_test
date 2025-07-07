    // Tailwind CSS 다크 모드 및 사용자 정의 테마 설정
    tailwind.config = {
      darkMode: 'class', // 클래스 기반 다크 모드 활성화
      theme: {
        extend: {
          fontFamily: {
            sans: ['Inter', 'system-ui', 'sans-serif'],
          },
          colors: {
            // 새로운 색상 팔레트
            primary: {
              DEFAULT: '#4f46e5', // indigo-600
              hover: '#4338ca', // indigo-700
              light: '#c7d2fe', // indigo-200
            },
            secondary: '#7c3aed', // violet-600
            slate: {
                50: '#f8fafc',
                100: '#f1f5f9',
                200: '#e2e8f0',
                300: '#cbd5e1',
                400: '#94a3b8',
                500: '#64748b',
                600: '#475569',
                700: '#334155',
                800: '#1e293b',
                900: '#0f172a',
                950: '#020617'
            }
          },
          animation: {
            'fade-in': 'fadeIn 0.15s ease-in-out forwards',
            'slide-up': 'slideUp 0.15s ease-out forwards',
          },
          keyframes: {
            fadeIn: {
              '0%': { opacity: '0' },
              '100%': { opacity: '1' },
            },
            slideUp: {
              '0%': { transform: 'translateY(20px)', opacity: '0' },
              '100%': { transform: 'translateY(0)', opacity: '1' },
            }
          }
        }
      }
    }

    // React 및 React Router 훅 가져오기
    const { useState, useEffect, useRef } = React;
    const { BrowserRouter, Switch, Route, Link, useLocation, useHistory } = ReactRouterDOM;

    const nginxBase = window.location.protocol + '//' + window.location.hostname + ':8080';

    // API 요청 래퍼 함수
    const apiFetch = async (url, options = {}) => {
      const token = localStorage.getItem('token');
      options.headers = options.headers || {};
      if (token) {
        options.headers['Authorization'] = 'Bearer ' + token;
      }
      const response = await fetch(url, options);
      if (response.status === 401) {
        localStorage.removeItem('token');
        window.location.href = '/';
        throw new Error('Unauthorized');
      }
      return response;
    };

    // [FIXED] 로그인/등록 폼 컴포넌트 분리
    const AuthForm = ({ isRegister, username, password, setUsername, setPassword, handleLogin, handleRegister, setMode }) => (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
            <div className="w-full max-w-md mx-auto animate-slide-up">
                <form onSubmit={isRegister ? handleRegister : handleLogin} className="bg-slate-900/50 backdrop-blur-lg border border-slate-700 p-8 rounded-2xl shadow-2xl space-y-6">
                    <div className="text-center">
                        <h2 className="text-3xl font-bold text-slate-100">{isRegister ? 'Create Account' : 'Welcome Back'}</h2>
                        <p className="text-slate-400 mt-2">{isRegister ? 'Join our platform today!' : 'Sign in to continue'}</p>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-slate-400 mb-2">Username</label>
                        <input type="text" className="w-full bg-slate-800 border border-slate-700 rounded-lg p-3 text-slate-100 focus:border-primary focus:outline-none transition" placeholder="Enter your username" value={username} onChange={e => setUsername(e.target.value)} />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-slate-400 mb-2">Password</label>
                        <input type="password" className="w-full bg-slate-800 border border-slate-700 rounded-lg p-3 text-slate-100 focus:border-primary focus:outline-none transition" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)} />
                    </div>
                    <button type="submit" className="btn-primary text-white py-3 px-6 rounded-lg font-semibold block mx-auto">{isRegister ? 'Register' : 'Login'}</button>
                    <p className="text-sm text-center text-slate-400">
                        {isRegister ? 'Already have an account?' : "Don't have an account?"}
                        <a href="#" onClick={(e) => { e.preventDefault(); setMode(isRegister ? 'login' : 'register'); }} className="font-medium text-primary-light hover:underline ml-1">
                            {isRegister ? 'Sign in' : 'Sign up'}
                        </a>
                    </p>
                </form>
            </div>
        </div>
    );

    // 사용자 정의 드롭다운 컴포넌트
    const CustomSelect = ({ options, value, onChange, placeholder = "Select..." }) => {
        const [isOpen, setIsOpen] = useState(false);
        const selectedOption = options.find(opt => opt.value === value) || null;
        const selectRef = useRef(null);

        const handleSelect = (option) => {
            onChange(option.value);
            setIsOpen(false);
        };

        useEffect(() => {
            const handleClickOutside = (event) => {
                if (selectRef.current && !selectRef.current.contains(event.target)) {
                    setIsOpen(false);
                }
            };
            document.addEventListener('mousedown', handleClickOutside);
            return () => document.removeEventListener('mousedown', handleClickOutside);
        }, []);

        return (
            <div className="custom-select relative" ref={selectRef}>
                <button
                    type="button"
                    onClick={() => setIsOpen(!isOpen)}
                    className="w-full px-4 py-2 border border-slate-600 rounded-lg focus:border-primary focus:outline-none transition-all duration-200 bg-slate-700 text-left flex items-center justify-between hover:border-slate-500"
                >
                    <span className={selectedOption ? "text-slate-100" : "text-slate-400"}>
                        {selectedOption ? selectedOption.label : placeholder}
                    </span>
                    <svg className={`w-5 h-5 text-slate-400 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                </button>

                {isOpen && (
                    <div className="absolute z-50 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-2xl backdrop-blur-md animate-fade-in">
                        <div className="py-1 max-h-60 overflow-auto">
                            {options.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => handleSelect(option)}
                                    className={`w-full px-4 py-3 text-left hover:bg-slate-700/50 hover:text-primary-light transition-all duration-150 flex items-center ${selectedOption?.value === option.value ? 'bg-primary/20 text-primary-light font-medium' : 'text-slate-200'}`}
                                >
                                    <span>{option.label}</span>
                                    {selectedOption?.value === option.value && (
                                        <svg className="w-4 h-4 ml-auto text-primary-light" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                                    )}
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    // 상태 배지 컴포넌트
    const StatusBadge = ({ status }) => {
        const getStatusInfo = (status) => {
            switch (status) {
                case 'running': return { class: 'status-running pulse', text: 'Running', bg: 'bg-green-500/10', text_color: 'text-green-400' };
                case 'stopped': return { class: 'status-stopped', text: 'Stopped', bg: 'bg-red-500/10', text_color: 'text-red-400' };
                case 'stopping': return { class: 'status-stopping pulse', text: 'Stopping', bg: 'bg-amber-500/10', text_color: 'text-amber-400' };
                case 'starting': return { class: 'status-starting pulse', text: 'Starting', bg: 'bg-blue-500/10', text_color: 'text-blue-400' };
                case 'building': return { class: 'status-building pulse', text: 'Building', bg: 'bg-blue-500/10', text_color: 'text-blue-400' };
                case 'deploying': return { class: 'status-deploying pulse', text: 'Deploying', bg: 'bg-blue-500/10', text_color: 'text-blue-400' };
                default: return { class: '', text: 'Unknown', bg: 'bg-slate-500/10', text_color: 'text-slate-400' };
            }
        };
        const statusInfo = getStatusInfo(status);
        return (
            <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${statusInfo.bg} ${statusInfo.text_color}`}>
                <span className={`status-indicator ${statusInfo.class} mr-1.5`}></span>
                {statusInfo.text}
            </span>
        );
    };

    // 진행률 바 컴포넌트
    const ProgressBar = ({ progress }) => (
        <div className="w-full bg-slate-700 rounded-full h-2 overflow-hidden">
            <div className="progress-bar h-2 rounded-full" style={{ width: `${progress}%` }}></div>
        </div>
    );

    // 메인 앱 컴포넌트
    function AppRoutes() {
        const location = useLocation();
        const history = useHistory();
        const [token, setToken] = useState(localStorage.getItem('token') || '');
        const [username, setUsername] = useState('');
        const [password, setPassword] = useState('');
        const [name, setName] = useState('');
        const [description, setDescription] = useState('');
        const [runType, setRunType] = useState('gradio');
        const [vramRequired, setVramRequired] = useState('0');
        const [files, setFiles] = useState([]);
        const [dragActive, setDragActive] = useState(false);
        const [apps, setApps] = useState([]);
        const [users, setUsers] = useState([]);
        const [logs, setLogs] = useState({});
        const [showLogs, setShowLogs] = useState({});
        const [uploadMsg, setUploadMsg] = useState('');
        const [uploadProgress, setUploadProgress] = useState(0);
        const [templates, setTemplates] = useState([]);
        const [editId, setEditId] = useState(null);
        const [editName, setEditName] = useState('');
        const [editDesc, setEditDesc] = useState('');
        const [tEditId, setTEditId] = useState(null);
        const [tEditName, setTEditName] = useState('');
        const [tEditDesc, setTEditDesc] = useState('');
        const [tEditVram, setTEditVram] = useState('0');
        const [openMenus, setOpenMenus] = useState({});
        const [openTemplateMenus, setOpenTemplateMenus] = useState({});
        const [isAdmin, setIsAdmin] = useState(false);
        const [currentUser, setCurrentUser] = useState('');
        const [mode, setMode] = useState('login');
        const [deployingApps, setDeployingApps] = useState([]);
        const [deployingTemplates, setDeployingTemplates] = useState({});
        const [savingTemplates, setSavingTemplates] = useState({});

        // 메뉴 외부 클릭 시 닫기
        useEffect(() => {
            const handleClickOutside = () => {
                setOpenMenus({});
                setOpenTemplateMenus({});
            };
            document.addEventListener('click', handleClickOutside);
            return () => document.removeEventListener('click', handleClickOutside);
        }, []);
        
        // 로그인/등록 처리
        if (!token) {
            const handleLogin = async (e) => {
                e.preventDefault();
                try {
                    const res = await apiFetch('/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: new URLSearchParams({ username, password })
                    });
                    const data = await res.json();
                    if (data.access_token) {
                        localStorage.setItem('token', data.access_token);
                        setToken(data.access_token);
                        window.location.href = '/';

                    } else {
                        alert('Login failed');
                    }
                } catch (err) {
                    alert('Login failed');
                }
            };

            const handleRegister = async (e) => {
                e.preventDefault();
                try {
                    const res = await apiFetch('/register', {
                        method: 'POST',
                        body: new URLSearchParams({ username, password })
                    });
                    if (res.ok) {
                        alert('User created');
                        setMode('login');
                    } else {
                        alert('Registration failed');
                    }
                } catch (err) {
                    alert('Registration failed');
                }
            };
            
            return (
                <AuthForm
                    isRegister={mode === 'register'}
                    username={username}
                    password={password}
                    setUsername={setUsername}
                    setPassword={setPassword}
                    handleLogin={handleLogin}
                    handleRegister={handleRegister}
                    setMode={setMode}
                />
            );
        }

        // 데이터 가져오기 및 상태 폴링
        useEffect(() => {
            const fetchData = async () => {
                try {
                    const [statusRes, tmplRes, userRes] = await Promise.all([
                        apiFetch('/status'),
                        apiFetch('/templates'),
                        apiFetch('/users/me')
                    ]);
                    const statusData = await statusRes.json();
                    setApps(statusData);
                    const tmplData = await tmplRes.json();
                    setTemplates(tmplData);
                    const userData = userRes.ok ? await userRes.json() : null;
                    if (userData) {
                        setIsAdmin(userData.is_admin);
                        setCurrentUser(userData.username);
                        if (userData.is_admin) {
                            const userListRes = await apiFetch('/users');
                            if (userListRes.ok) {
                                setUsers(await userListRes.json());
                            }
                        }
                    }
                } catch (error) {
                    console.error("Failed to fetch initial data:", error);
                }
            };
            fetchData();
        }, [token]);

        const refreshStatus = async () => {
            try {
                const res = await apiFetch('/status');
                const data = await res.json();
                const existingIds = new Set(data.map(a => a.id));
                const remainingDeploying = deployingApps.filter(d => !existingIds.has(d.id));
                setDeployingApps(remainingDeploying);
                const newDeployingTemplates = { ...deployingTemplates };
                Object.entries(deployingTemplates).forEach(([tid, aid]) => {
                    if (existingIds.has(aid)) delete newDeployingTemplates[tid];
                });
                setDeployingTemplates(newDeployingTemplates);
                setApps([...remainingDeploying, ...data]);
            } catch (error) {
                console.error("Failed to refresh status:", error);
            }
        };

        useEffect(() => {
            const interval = setInterval(refreshStatus, 1000);
            return () => clearInterval(interval);
        }, [deployingApps, deployingTemplates]);
        
        const handleDragOver = (e) => { e.preventDefault(); e.stopPropagation(); if (!dragActive) setDragActive(true); };
        const handleDragLeave = (e) => { e.preventDefault(); e.stopPropagation(); setDragActive(false); };
        const handleDrop = (e) => {
            e.preventDefault(); e.stopPropagation(); setDragActive(false);
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                setFiles(e.dataTransfer.files);
                e.dataTransfer.clearData();
            }
        };
        
        const handleUpload = async (e) => {
            e.preventDefault();
            if (files.length === 0) {
                setUploadMsg('Error: Please select a file to upload.');
                return;
            }
        
            setUploadMsg('Upload started...');
            setUploadProgress(50);
        
            const formData = new FormData();
            formData.append('name', name);
            formData.append('description', description);
            formData.append('file', files[0]);
            formData.append('vram_required', vramRequired);
        
            try {
                const res = await apiFetch('/upload', {
                    method: 'POST',
                    body: formData,
                });

                const data = await res.json();

                if (res.ok) {
                    setName('');
                    setDescription('');
                    setRunType('gradio');
                    setVramRequired('0');
                    setFiles([]);
                    await refreshStatus();
                    setUploadProgress(100);
                    setTimeout(() => {
                        setUploadProgress(0);
                        setUploadMsg('Upload finished: ' + (data.app_id || ''));
                    }, 500);
                } else {
                    setUploadProgress(100);
                    setTimeout(() => {
                        setUploadProgress(0);
                        setUploadMsg('Error: ' + (data.detail || 'upload failed'));
                    }, 500);
                }
            } catch (error) {
                setUploadProgress(100);
                setTimeout(() => {
                    setUploadProgress(0);
                    setUploadMsg('Error uploading app.');
                }, 500);
                console.error("Upload error:", error);
            }
        };

        const toggleLogs = async (appId) => {
            if (showLogs[appId]) {
                setShowLogs(prev => ({ ...prev, [appId]: false })); return;
            }
            try {
                const res = await apiFetch(`/logs/${appId}`);
                const text = await res.text();
                setLogs(prev => ({ ...prev, [appId]: text }));
                setShowLogs(prev => ({ ...prev, [appId]: true }));
            } catch {
                setLogs(prev => ({ ...prev, [appId]: 'Failed to load logs.' }));
                setShowLogs(prev => ({ ...prev, [appId]: true }));
            }
        };
        const toggleMenu = (appId, e) => { e.stopPropagation(); setOpenMenus(prev => ({ [appId]: !prev[appId] })); };
        const closeMenu = (appId) => setOpenMenus(prev => ({ ...prev, [appId]: false }));
        const toggleTemplateMenu = (id, e) => { e.stopPropagation(); setOpenTemplateMenus(prev => ({ [id]: !prev[id] })); };
        const closeTemplateMenu = (id) => setOpenTemplateMenus(prev => ({ ...prev, [id]: false }));
        const stopApp = async (id) => { await apiFetch(`/stop/${id}`, { method: 'POST' }); refreshStatus(); };
        const restartApp = async (id) => { await apiFetch(`/restart/${id}`, { method: 'POST' }); refreshStatus(); };
        const deleteApp = async (id) => {
            await apiFetch(`/apps/${id}`, { method: 'DELETE' });
            refreshStatus();
        };
        const deployTemplate = async (id) => {
            setDeployingTemplates(prev => ({ ...prev, [id]: true }));
            const template = templates.find(tmp => tmp.id === id) || {};
            try {
                const form = new FormData();
                form.append('vram_required', template.vram_required);
                const res = await apiFetch(`/deploy_template/${id}`, { method: 'POST', body: form });
                const data = await res.json();
                const placeholder = { id: data.app_id, name: template.name || id, description: template.description || '', status: 'deploying', url: data.url, gpus: [] };
                setDeployingApps(prev => [...prev, placeholder]);
                setDeployingTemplates(prev => ({ ...prev, [id]: data.app_id }));
                setApps(prev => [placeholder, ...prev]);
            } catch {
                setDeployingTemplates(prev => { const n = { ...prev }; delete n[id]; return n; });
            }
        };
        const saveTemplate = async (id) => {
            setSavingTemplates(prev => ({ ...prev, [id]: true }));
            try {
                await apiFetch(`/save_template/${id}`, { method: 'POST' });
                const res = await apiFetch('/templates');
                setTemplates(await res.json());
                alert('Template saved');
            } catch { alert('Failed to save template'); }
            finally { setSavingTemplates(prev => ({ ...prev, [id]: false })); }
        };
        const startTemplateEdit = (t) => {
            setTEditId(t.id);
            setTEditName(t.name || '');
            setTEditDesc(t.description || '');
            setTEditVram(String(t.vram_required || 0));
        };
        const cancelTemplateEdit = () => {
            setTEditId(null);
            setTEditName('');
            setTEditDesc('');
            setTEditVram('0');
        };
        const saveTemplateEdit = async () => {
            await apiFetch('/edit_template', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    template_id: tEditId,
                    name: tEditName,
                    description: tEditDesc,
                    vram_required: parseInt(tEditVram || '0', 10)
                })
            });
            const res = await apiFetch('/templates');
            setTemplates(await res.json());
            cancelTemplateEdit();
        };
        const deleteTemplate = async (id) => {
            await apiFetch(`/templates/${id}`, { method: 'DELETE' });
            const res = await apiFetch('/templates');
            setTemplates(await res.json());
        };
        const startEdit = (app) => { setEditId(app.id); setEditName(app.name || ''); setEditDesc(app.description || ''); };
        const cancelEdit = () => { setEditId(null); setEditName(''); setEditDesc(''); };
        const saveEdit = async () => {
            await apiFetch('/edit_app', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app_id: editId, name: editName, description: editDesc }) });
            refreshStatus(); cancelEdit();
        };
        const handleResetPassword = async (id) => {
            const pw = prompt('New password:');
            if (!pw) return;
            await apiFetch(`/users/${id}/reset_password`, { method: 'POST', body: new URLSearchParams({ new_password: pw }) });
            alert('Password reset');
        };

        return (
            <>
            {editId && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
                    <div className="bg-slate-800 border border-slate-600 rounded-lg p-6 w-96 space-y-4">
                        <h3 className="text-xl font-semibold text-slate-100">Edit App</h3>
                        <div>
                            <label className="block text-sm font-medium text-slate-400 mb-1">Name</label>
                            <input type="text" className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100" value={editName} onChange={e => setEditName(e.target.value)} />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-slate-400 mb-1">Description</label>
                            <textarea rows="3" className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100" value={editDesc} onChange={e => setEditDesc(e.target.value)} />
                        </div>
                        <div className="flex justify-end space-x-2">
                            <button onClick={cancelEdit} className="px-4 py-2 rounded-md bg-slate-600 text-sm">Cancel</button>
                            <button onClick={saveEdit} className="px-4 py-2 rounded-md bg-primary text-white text-sm">Save</button>
                        </div>
                    </div>
                </div>
            )}
            {tEditId && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
                    <div className="bg-slate-800 border border-slate-600 rounded-lg p-6 w-96 space-y-4">
                        <h3 className="text-xl font-semibold text-slate-100">Edit Template</h3>
                        <div>
                            <label className="block text-sm font-medium text-slate-400 mb-1">Name</label>
                            <input type="text" className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100" value={tEditName} onChange={e => setTEditName(e.target.value)} />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-slate-400 mb-1">Description</label>
                            <textarea rows="3" className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100" value={tEditDesc} onChange={e => setTEditDesc(e.target.value)} />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-slate-400 mb-1">VRAM (MB)</label>
                            <input type="number" className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100" value={tEditVram} onChange={e => setTEditVram(e.target.value)} />
                        </div>
                        <div className="flex justify-end space-x-2">
                            <button onClick={cancelTemplateEdit} className="px-4 py-2 rounded-md bg-slate-600 text-sm">Cancel</button>
                            <button onClick={saveTemplateEdit} className="px-4 py-2 rounded-md bg-primary text-white text-sm">Save</button>
                        </div>
                    </div>
                </div>
            )}
            <div className="min-h-screen bg-slate-900">
                {/* Header */}
                <header className="bg-slate-900/70 backdrop-blur-lg border-b border-slate-700/50 sticky top-0 z-50">
                    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                        <div className="flex justify-between items-center py-4">
                            <div className="flex items-center space-x-3">
                                <div className="w-9 h-9 bg-gradient-to-r from-primary to-secondary rounded-lg flex items-center justify-center shadow-lg">
                                    <span className="text-white font-bold text-lg">A</span>
                                </div>
                                <Link to="/" className="text-xl font-bold bg-gradient-to-r from-slate-200 to-slate-400 bg-clip-text text-transparent">AI Portal</Link>
                            </div>
                            
                            <nav className="flex items-center space-x-2 bg-slate-800 rounded-lg p-1">
                                {[{path: '/', label: 'Create App'}, {path: '/apps', label: `My Apps (${apps.length})`}, isAdmin && {path: '/user-admin', label: 'Users'}].filter(Boolean).map(item => (
                                    <Link key={item.path} to={item.path} className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200 ${location.pathname === item.path ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-white'}`}>{item.label}</Link>
                                ))}
                            </nav>

                            <div className="flex items-center space-x-4">
                                {currentUser && <span className="text-sm text-slate-400">Welcome, {currentUser}</span>}
                                <button onClick={() => { localStorage.removeItem('token'); setToken(''); setMode('login'); window.location.href = '/'; }} className="px-3 py-1.5 rounded-md text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-700 transition-colors">Logout</button>

                            </div>
                        </div>
                    </div>
                </header>

                <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
                    <Switch>
                        <Route exact path="/">
                            <div className="max-w-3xl mx-auto">
                                <div className="grid grid-cols-1 gap-8">

                                {/* Upload Form */}
                                <div className="space-y-6 animate-slide-up">
                                    <div className="bg-slate-800/50 backdrop-blur-lg border border-slate-700 rounded-2xl shadow-2xl p-8">
                                        <div className="flex items-center space-x-4 mb-6">
                                            <div className="w-12 h-12 bg-gradient-to-br from-primary to-secondary rounded-xl flex items-center justify-center shadow-lg"><span className="text-white text-2xl font-bold">+</span></div>
                                            <h2 className="text-2xl font-bold text-slate-100">Deploy New App</h2>
                                        </div>
                                        
                                        <form onSubmit={handleUpload} className="space-y-6">
                                            {/* Form Fields */}
                                            <div>
                                                <label className="block text-sm font-medium text-slate-400 mb-2">App Name</label>
                                                <input type="text" className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100 focus:border-primary focus:outline-none transition" placeholder="My Awesome AI App" value={name} onChange={e => setName(e.target.value)} />
                                            </div>
                                            <div>
                                                <label className="block text-sm font-medium text-slate-400 mb-2">Description</label>
                                                <input type="text" className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100 focus:border-primary focus:outline-none transition" placeholder="Brief description of your app..." value={description} onChange={e => setDescription(e.target.value)} />
                                                {/* <textarea className="w-full bg-slate-700 border border-slate-600 rounded-lg p-2 text-slate-100 focus:border-primary focus:outline-none transition" placeholder="Brief description of your app..." rows="3" value={description} onChange={e => setDescription(e.target.value)} />                                 */}
                                            </div>
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                                <div>
                                                    <label className="block text-sm font-medium text-slate-400 mb-2">Runtime</label>
                                                    <CustomSelect options={[{ value: 'gradio', label: 'Gradio' }, { value: 'docker', label: 'Docker' }]} value={runType} onChange={(value) => setRunType(value)} />                            
                                                </div>
                                                <div>
                                                    <label className="block text-sm font-medium text-slate-400 mb-2">VRAM (MB)</label>
                                                    <input type="number" className="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-2 text-slate-100 focus:border-primary focus:outline-none transition" placeholder="0" value={vramRequired} onChange={e => setVramRequired(e.target.value)} />
                                                </div>
                                            </div>
                                            <div>
                                                <label className="block text-sm font-medium text-slate-400 mb-2">Upload Files</label>
                                                <div className={`upload-area border-2 border-dashed rounded-lg p-8 text-center ${dragActive ? 'drag-active' : ''}`} onDragOver={handleDragOver} onDragEnter={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
                                                    <input type="file" className="hidden" id="file-upload" onChange={e => setFiles(e.target.files)} multiple />
                                                    <label htmlFor="file-upload" className="cursor-pointer">
                                                        <svg className="mx-auto h-12 w-12 text-slate-500" stroke="currentColor" fill="none" viewBox="0 0 48 48" aria-hidden="true"><path d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                                                        <p className="mt-4 text-sm text-slate-300">Click to upload or <span className="font-semibold text-primary-light">drag and drop</span></p>
                                                        <p className="text-xs text-slate-500 mt-1">ZIP, PY, or any project files</p>
                                                        {files.length > 0 && <p className="mt-3 text-sm text-primary-light font-medium">{files.length} file(s) selected</p>}
                                                    </label>
                                                </div>
                                            </div>
                                            <button type="submit" className="btn-primary text-white py-2 px-4 rounded-lg font-semibold text-base shadow-lg block">Deploy App</button>
                                        </form>
                                        {/* Upload Status */}
                                        {uploadProgress > 0 && (
                                            <div className="mt-4">
                                                <div className="flex justify-between text-sm text-slate-400 mb-2"><span>Uploading...</span></div>
                                                <ProgressBar progress={uploadProgress} />
                                            </div>
                                        )}
                                        {uploadMsg && (
                                            <div className={`mt-4 p-3 rounded-lg text-sm flex items-start justify-between ${uploadMsg.includes('Error') ? 'bg-red-500/10 text-red-400 border border-red-500/20' : 'bg-green-500/10 text-green-400 border border-green-500/20'}`}>
                                                <span>{uploadMsg}</span>
                                                <button onClick={() => setUploadMsg('')} className="ml-2 text-slate-400 hover:text-slate-200">&times;</button>
                                            </div>
                                        )}
                                    </div>
                                </div>
                                {/* Templates */}
                                <div className="space-y-6 animate-slide-up">
                                    <div className="bg-slate-800/50 backdrop-blur-lg border border-slate-700 rounded-2xl shadow-2xl p-8">
                                        <div className="flex items-center space-x-4 mb-6">
                                            <div className="w-12 h-12 bg-gradient-to-br from-emerald-500 to-teal-500 rounded-xl flex items-center justify-center shadow-lg"><span className="text-white text-2xl">⚡️</span></div>
                                            <h2 className="text-2xl font-bold text-slate-100">Templates</h2>
                                        </div>
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pr-2">
                                            {templates.length > 0 ? templates.map(t => (
                                                <div key={t.id} className="bg-slate-900/50 border border-slate-700 rounded-lg p-4 relative">

                                                    <div className="flex justify-between items-start">
                                                        <h3 className="font-semibold text-slate-100">{t.name}</h3>
                                                        <div className="relative z-10" onClick={e => e.stopPropagation()}>
                                                            <button onClick={(e) => toggleTemplateMenu(t.id, e)} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-700 text-slate-400">⋯</button>
                                                            {openTemplateMenus[t.id] && (
                                                                <div className="absolute right-0 mt-2 w-40 bg-slate-800 border border-slate-700 rounded-lg shadow-2xl z-20 animate-fade-in">
                                                                    <a onClick={() => { startTemplateEdit(t); closeTemplateMenu(t.id); }} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 cursor-pointer">Edit</a>
                                                                    <a onClick={() => { deleteTemplate(t.id); closeTemplateMenu(t.id); }} className="block w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-red-500/20 cursor-pointer">Delete</a>
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                    <p className="text-sm text-slate-400 mt-1">{t.description}</p>
                                                    <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-slate-500">
                                                        <span className="whitespace-nowrap">Type: {t.type}</span>
                                                        <span className="whitespace-nowrap">VRAM: {t.vram_required} MB</span>
                                                    </div>
                                                    <button onClick={() => deployTemplate(t.id)} disabled={deployingTemplates[t.id]} className="mt-4 btn-primary text-white py-1.5 px-3 rounded-md block">{deployingTemplates[t.id] ? 'Deploying...' : 'Deploy'}</button>
                                                </div>
                                            )) : <p className="text-slate-400 text-center py-8">No templates available.</p>}
                                        </div>
                                    </div>
                                </div>
                            </div>
                            </div>
                        </Route>
                        
                        <Route path="/apps">
                            <div className="space-y-8 animate-fade-in">
                                <div className="text-center">
                                    <h2 className="text-4xl font-bold text-slate-100">Your AI Applications</h2>
                                    <p className="text-slate-400 mt-2">Manage and monitor your deployed applications</p>
                                </div>
                                {apps.length === 0 ? (
                                    <div className="bg-slate-800/50 border border-slate-700 rounded-2xl p-12 text-center">
                                        <h3 className="text-xl font-semibold text-slate-100">No apps deployed yet</h3>
                                        <p className="text-slate-400 my-4">Get started by creating your first AI application.</p>
                                        <Link to="/" className="btn-primary text-white px-6 py-3 rounded-lg font-medium inline-block">Create Your First App</Link>
                                    </div>
                                ) : (
                                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                                        {apps.map(app => (
                                            <div key={app.id} onClick={() => app.url && app.status === 'running' && window.open(`${nginxBase}${app.url}`, '_blank')} className="bg-slate-800/50 backdrop-blur-lg border border-slate-700 rounded-2xl p-6 card-hover relative overflow-hidden flex flex-col justify-between cursor-pointer">
                                                <div>
                                                    <div className="flex justify-between items-start">
                                                        <div className="w-12 h-12 bg-gradient-to-br from-primary to-secondary rounded-xl flex items-center justify-center mb-4 shadow-lg">
                                                            <span className="text-white font-bold text-2xl">{(app.name || app.id).charAt(0).toUpperCase()}</span>
                                                        </div>
                                                        <div className="flex items-center space-x-2 z-10" onClick={e => e.stopPropagation()}>
                                                            <StatusBadge status={app.status} />
                                                            <div className="relative">
                                                                <button onClick={(e) => toggleMenu(app.id, e)} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-700 text-slate-400">⋯</button>
                                                                {openMenus[app.id] && (
                                                                    <div className="absolute right-0 mt-2 w-40 bg-slate-800 border border-slate-700 rounded-lg shadow-2xl z-20 animate-fade-in">
                                                                        <a onClick={() => { toggleLogs(app.id); closeMenu(app.id); }} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 cursor-pointer">{showLogs[app.id] ? 'Hide Logs' : 'View Logs'}</a>
                                                                        <a onClick={() => { app.status === 'running' ? stopApp(app.id) : restartApp(app.id); closeMenu(app.id); }} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 cursor-pointer">{app.status === 'running' ? 'Stop' : 'Start'}</a>
                                                                        <a onClick={() => { startEdit(app); closeMenu(app.id); }} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 cursor-pointer">Edit</a>
                                                                        <a onClick={() => { saveTemplate(app.id); closeMenu(app.id); }} className="block w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 cursor-pointer" disabled={savingTemplates[app.id]}>{savingTemplates[app.id] ? 'Saving…' : 'Save as Template'}</a>
                                                                        <a onClick={() => { deleteApp(app.id); closeMenu(app.id); }} className="block w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-red-500/20 cursor-pointer">Delete App</a>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                    </div>
                                                    <h3 className="text-xl font-semibold text-slate-100 mb-1 truncate">{app.name || app.id}</h3>
                                                    <p className="text-xs text-slate-500 font-mono break-all">ID: {app.id}</p>
                                                    {app.description && <p className="text-sm text-slate-400 mt-3 h-10 line-clamp-2">{app.description}</p>}
                                                    {app.gpus && app.gpus.length > 0 && <div className="mt-3"><span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-purple-500/10 text-purple-400">🎮 GPU {app.gpus.join(',')}</span></div>}
                                                </div>
                                                
                                                {showLogs[app.id] && (
                                                    <div className="mt-4 border-t border-slate-700 pt-4" onClick={e => e.stopPropagation()}>
                                                        <div className="bg-slate-900 rounded-lg p-4 max-h-48 overflow-auto"><pre className="text-green-400 text-xs font-mono whitespace-pre-wrap">{logs[app.id] || 'Loading logs...'}</pre></div>
                                                    </div>
                                                )}

                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </Route>
                        {isAdmin && (
                        <Route path="/user-admin">
                            <div className="space-y-8 animate-fade-in">
                                <div className="text-center">
                                    <h2 className="text-4xl font-bold text-slate-100">User Management</h2>
                                    <p className="text-slate-400 mt-2">Manage registered users</p>
                                </div>
                                <div className="bg-slate-800/50 backdrop-blur-lg border border-slate-700 rounded-2xl p-8">
                                    <table className="min-w-full divide-y divide-slate-700 text-sm">
                                        <thead>
                                            <tr className="text-slate-400">
                                                <th className="px-4 py-2 text-left">Username</th>
                                                <th className="px-4 py-2">Role</th>
                                                <th className="px-4 py-2 text-right">Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-700">
                                            {users.map(u => (
                                                <tr key={u.id} className="hover:bg-slate-700/30">
                                                    <td className="px-4 py-2 text-slate-100">{u.username}</td>
                                                    <td className="px-4 py-2 text-center text-slate-300">{u.is_admin ? 'Admin' : 'User'}</td>
                                                    <td className="px-4 py-2 text-right">
                                                        <button onClick={() => handleResetPassword(u.id)} className="bg-primary text-white px-3 py-1 rounded-md text-xs hover:bg-primary-hover">Reset Password</button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </Route>
                        )}
                    </Switch>
                </main>
                
                <footer className="border-t border-slate-700/50 mt-16">
                    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 text-center text-slate-500">
                        <p className="text-sm">AI App Portal</p>
                        <p className="text-xs mt-2">© {new Date().getFullYear()} - All rights reserved.</p>
                    </div>
                </footer>
            </div>
            </>
        );
    }

    function App() {
        return (
            <BrowserRouter>
                <AppRoutes />
            </BrowserRouter>
        );
    }

    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
