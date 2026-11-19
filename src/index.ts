// SPDX-License-Identifier: MIT
import express from 'express';

const app = express();

app.get('/', (req, res) => {
  res.send('Hello, Kaine!');
});

const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`Server listening on port ${port}`);
});

export default app;