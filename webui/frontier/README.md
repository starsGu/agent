# 基于react的前端项目，类似于chatgpt网页版

**单页网页SPA**


## 组件    
    agentState = useState(false)
    refreshTime = useState(0)
    useEffect(()=>{
        agentState 由 get http://127.0.0.1:8000/agentState 得到
    },[refreshTime])


    顶层菜单栏 会话，设置，agent状态
        会话下拉列表：
        设置：
            暂时保留
        if agentState then 已连接
        else 未连接 重连button onclick = ()=>{setRefreshTime((value)->value+1)}


    
    content组件，左边会话栏，右边chat页面, if agentState else 空白
        chatMessages = useState()
        sessions = useState()
        currentSession = useState()
        refreshKey = useState(0)

        useEffect(()=>{
            Sessions 由 get http://127.0.0.1:8000/agentSessions 得到
            if currentSession 不为空
                chatMessages 由 get http://127.0.0.1:8000/agent?session_id={currentSession} 得到
        },[refreshKey, currentSession])
        

        **会话栏(sessions)固定可滚动**
            根据 sessions 渲染一条条会话。每个 session 组件有自己的 session_id
            每个 sessions 组件 onclick = ()=>{setCurrentSession(session_id)}，
            每个 session 组建的右边有个叉 ，单击 删除会话 onclick = ()=>{http://127.0.0.1:8000/sessions?session_id={session_id}}
                if 删除的是currentSession， currentSession = null
                setRefreshKey(value => value + 1)
            列表下面有一个新建列表，onclick = {setCurrentSession(null)}


        **chat组件**，
            message组件(chatMessages)
                if currentSession 为空 渲染空
                else 根据 chatMessages 渲染一条条对话。

            input组件：
                text input： 输入用户提问
                send button： onclick
                    post:http://127.0.0.1:8000/chat
                    targetSession = if currentSession 为空 then 创建"text input的前四个字符+随机数" else currentSession
                    {
                        "human_message": text input 的内容,
                        "session_id": targetSession
                    }
                    setCurrentSession(targetSession)
                    setRefreshKey(value => value + 1)
