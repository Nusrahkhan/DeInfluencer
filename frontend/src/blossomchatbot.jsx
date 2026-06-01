import React, { useState } from 'react';
import dellaProfile from './assets/chatbot/della-profile.jpg';
import sariahProfile from './assets/chatbot/sariah-profile.svg';
import {
 Heart,
 Plus,
 Info,
 Edit3,
 Settings,
 ArrowRight,
 Paperclip,
 Sparkles,
 Crown
} from 'lucide-react';
import './MonaChatbot.css';

const routine = [
  ['🧴', 'Skincare Routine', '3 days ago'],
  ['💄', 'Summer Lipsticks', '5 days ago'],
  ['🪞', 'Wedding Makeup', '1 week ago'],
  ['🧴', 'Acne Solutions', '1 week ago'],
  ['♡', 'Budget Beauty', '2 weeks ago'],
];
const prompts = ['Best sunscreen for oily skin', 'Lip tint under ₹500', 'Serum for acne scars', 'Dupe for Charlotte Tilbury', 'Makeup that lasts all day'];


function LeftRail({ onPrompt, onNewChat }) {
  return (
    <aside className="left-rail">
      <header className="brand">
        <h1>delnfluence</h1>
        <h7>Your personal beauty dermat suggestor.</h7>
      </header>

      <button className="new-chat" onClick={onNewChat}>
        <Plus size={18} /> New Chat
      </button>

      <section className="ask">
        <h3>
          Try asking Blossom <Sparkles size={15} />
        </h3>

        {prompts.map((p) => (
          <button key={p} onClick={() => onPrompt(p)}>
            <Heart size={14} />
            {p}
          </button>
        ))}
      </section>
    </aside>
  );
}

function Chat({
 message,
 setMessage,
 messages,
 loading,
 onSend,
 isNewChat
}) {
 return <main className="chat">
   <header className="chat-top"><div className="della-avatar"><img src={dellaProfile} alt="Blossom"/></div><div><h2>Blossom</h2><p>Your personal beauty investigator.</p></div><button>About Blossom <Info size={16}/></button></header>
   <div className={`conversation ${isNewChat?'fresh-chat':''}`}>
    {isNewChat&&<div className="della-reply welcome-reply"><div className="mini-avatar"><img src={dellaProfile} alt="Blossom"/></div><p>Hi beautiful, how can I help you?</p></div>}
      {messages.map((msg, index) =>
        msg.role === "user" ? (
          <div key={index} className="chat-exchange">
            <div className="user-msg">
              {msg.content}
            </div>
            <small className="time">Just now</small>
          </div>
        ) : (
          <div key={index} className="della-reply">
            <div className="mini-avatar">
              <img
                src={dellaProfile}
                alt="Blossom"
              />
            </div>

            <p>{msg.content}</p>
          </div>
        )
      )}

      {loading && (
        <div className="della-reply">
          <div className="mini-avatar">
            <img
              src={dellaProfile}
              alt="Blossom"
            />
          </div>

          <p>Thinking...</p>
        </div>
      )}
     </div>
   <footer><div className="input"><Paperclip size={20}/><input value={message} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>e.key==='Enter'&&onSend()} placeholder="Ask Blossom anything about beauty..."/><button onClick={onSend}><ArrowRight size={22}/></button></div></footer>
 </main>
}
function RightRail({profile,onEdit}) {
 return <aside className="right-rail">
   <section className="profile"><div className="profile-top"><div className="photo"><img src={sariahProfile} alt="Sariah profile"/></div><div><h2>Sariah’s Profile <Edit3 size={15}/></h2><p>View & update your beauty profile</p></div></div>
   {Object.entries(profile).map(([k,v])=><div className="profile-row" key={k}><b>{k}</b><span>{v}</span></div>)}<button onClick={onEdit}>Edit Profile <Settings size={18}/></button></section>
   <section className="helps"><h3>How Blossom helps <Heart size={14}/></h3>{['Personalizes picks for your skin & preferences','Saves you time & money'].map(x=><p key={x}>♡ <span>{x}</span></p>)}</section>
   <section className="promise"><h3>delnfluence Promise</h3><p>We’re not here to sell you hype.<br/>We’re here to help you find what<br/>actually works.</p><b>♡</b></section>
   <section className="premium"><h3>Unlock deeper insights</h3><p>Get detailed review breakdowns,<br/>ingredient analysis & more.</p><button>Go Premium <Crown size={14}/></button><strong>♥</strong></section>
 </aside>
}
function ProfileModal({profile,onSave,onClose}){const [draft,setDraft]=useState(profile);return <div className="modal-backdrop"><form className="profile-modal" onSubmit={e=>{e.preventDefault();onSave(draft)}}><div className="modal-head"><div><h2>Edit Profile</h2><p>Keep your beauty profile up to date.</p></div><button type="button" onClick={onClose}>×</button></div>{Object.entries(draft).map(([key,value])=><label key={key}><span>{key}</span><input value={value} onChange={e=>setDraft({...draft,[key]:e.target.value})}/></label>)}<div className="modal-actions"><button type="button" onClick={onClose}>Cancel</button><button type="submit">Save Profile</button></div></form></div>}
function App(){
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message,setMessage]=useState('');
  const [isNewChat,setIsNewChat]=useState(false);
  const [isEditing,setIsEditing]=useState(false);
  const [profile,setProfile]=useState({'Skin Type':'Oily','Concerns':'Acne, Hyperpigmentation','Budget':'₹₹ (Mid range)','Preferred Brands':'Rare Beauty, e.l.f., The Ordinary, Minimalist'});
  const send = async () => {
  const text = message.trim();

  if (!text || loading) return;

  const userMessage = {
    role: "user",
    content: text,
  };

  setMessages(prev => [...prev, userMessage]);
  setMessage("");
  setLoading(true);
  setIsNewChat(false);

  try {
    const response = await fetch(
      "http://localhost:8000/chatbot",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: text,
          profile: {
            skin_type: profile["Skin Type"],
            concerns: profile["Concerns"],
            budget: profile["Budget"],
            preferred_brands: profile["Preferred Brands"],
          },
        }),
      }
    );

    const data = await response.json();

    setMessages(prev => [
      ...prev,
      {
        role: "assistant",
        content: data.answer,
      },
    ]);
  } catch (err) {
    setMessages(prev => [
      ...prev,
      {
        role: "assistant",
        content:
          "Sorry, I couldn't connect to the beauty assistant.",
      },
    ]);
  } finally {
    setLoading(false);
  }
};
const newChat = () => {
  setMessage("");
  setMessages([]);
  setIsNewChat(true);
};
return <div className="app"><LeftRail onPrompt={setMessage} onNewChat={newChat}/>
<Chat
 message={message}
 setMessage={setMessage}
 messages={messages}
 loading={loading}
 onSend={send}
 isNewChat={isNewChat}
/>
<RightRail profile={profile} onEdit={()=>setIsEditing(true)}/>
  {isEditing&&<ProfileModal profile={profile} onClose={()=>setIsEditing(false)} onSave={value=>{setProfile(value);setIsEditing(false)}}/>}</div>}
export default App;