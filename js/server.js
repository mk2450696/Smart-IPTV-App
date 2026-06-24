const express = require('express');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const app = express();
const PORT = 3000;

// Serve HTML form
app.use(express.static(path.join(__dirname, 'public')));
app.use(bodyParser.urlencoded({ extended: true }));

app.post('/update-credentials', (req, res) => {
    const { username, password } = req.body;

    if (!username || !password) {
        return res.send('Both username and password are required!');
    }

    const jsFile = path.join(__dirname, 'source.min.vidaa.js');
    let content = fs.readFileSync(jsFile, 'utf-8');

    // Update only the LayerSevenTV credentials
    const regex = /name:"LayerSevenTV".*?username:"(.*?)",password:"(.*?)"/;
    if (!regex.test(content)) {
        return res.send('LayerSevenTV profile not found in iptv.js!');
    }

    content = content.replace(
        regex,
        `name:"LayerSevenTV",server:"http://hi-world.me",port:"80",username:"${username}",password:"${password}"`
    );

    fs.writeFileSync(jsFile, content, 'utf-8');
    res.sendFile(require('path').join(__dirname, 'public', 'update-success.html'));
});

app.listen(PORT, () => console.log(`Server running at http://localhost:${PORT}`));
