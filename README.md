# 노래 악기 분리기

노래 악기 사운드 조절해서 악보 따는 용으로 만듦.


# 다운 및 설치 방법

😺 1. 초록색 <> Code 버튼을 누르고 Download ZIP 클릭

<img width="529" height="370" alt="Image" src="https://github.com/user-attachments/assets/8871ed1a-e597-491b-b55e-4c5557925904" />

<br>
<p>&nbsp;</p>


😺 2. 폴더명은 뒤에 -main 남겨도 되고 지워도 됨. 지우는게 깔끔하겠네요~

<img width="350" height="86" alt="Image" src="https://github.com/user-attachments/assets/d8ba7e7c-727b-4766-8840-080c786ed46e" />

<br>
<p>&nbsp;</p>


😺 3. 압축을 풀면 안에 또 이런 폴더가 있는데 -main은 지우고 폴더명이 cyEbis가 되도록.

<img width="84" height="86" alt="Image" src="https://github.com/user-attachments/assets/1ddfe5c7-f647-4eb6-845b-9ab7b2ad32b8" />

<br>
<p>&nbsp;</p>

😺 4. cyEbis 폴더에 들어가면 backend 라는 폴더가 있습니다. 이 폴더 안으로 들어간 뒤 위에 보이는 주소장에서 cmd를 입력하고 엔터키를 누르세요.

<img width="735" height="380" alt="Image" src="https://github.com/user-attachments/assets/4744c367-0d44-45a1-a694-3af825a24853" />

<br>
<p>&nbsp;</p>

😺 5. 그 다음 처음 한 번만 아래 명령어들을 순서대로 복붙 후 엔터하면 됩니다.

```bat
python -m venv .venv
```

```bat
.\.venv\Scripts\python -m pip install --upgrade pip
```

```bat
.\.venv\Scripts\python -m pip install -r requirements.txt
```

<br>
<p>&nbsp;</p>

이러면 cmd 창에 텍스트들이 좌르르 뜰겁니다. 

<img width="830" height="695" alt="image" src="https://github.com/user-attachments/assets/9d89e130-02ef-4abe-9d45-ba6b458ef645" />

<br>
<p>&nbsp;</p>
완료되면 다음의 텍스트가 뜨고 멈춥니다.

<img width="523" height="95" alt="image" src="https://github.com/user-attachments/assets/a7752913-a4b8-4e3a-8bc0-ed14972dfcfd" />

<br>
<p>&nbsp;</p>

😺 5.1. 그래픽카드 사용 중이라면, 현재 cmd 창에서 아래의 명령어를 복붙 후 엔터키 누르세요


```bat
.\.venv\Scripts\python install_gpu_torch.py
```

<br>
<p>&nbsp;</p>

그럼 텍스트가 막 뜨면서 뭔가를 설치합니다.

<img width="843" height="409" alt="image" src="https://github.com/user-attachments/assets/5c79fc6c-173a-4e38-b493-5002f54acd66" />

<br>
<br>


<img width="846" height="249" alt="image" src="https://github.com/user-attachments/assets/9651ec66-525f-4dbf-b841-54759a15a87c" />


(완료된 모습)


<br>
<p>&nbsp;</p>


😺 6. 이제 cmd 창을 꺼도됩니다. 그 후 start_syebis 파일을 더블 클릭하면 cmd 창이 나오고 로컬 서버가 실행됩니다.

<img width="256" height="260" alt="image" src="https://github.com/user-attachments/assets/a5ba78f6-45e4-4a23-a942-4a5189934ade" />


<br>

실행하면 아래의 경고창이 뜨는데, 항상 확인 체크 해제하고 실행해주세요. 국민대 소프트웨어융합대학 이름을 걸고 바이러스 절대 아님.

<img width="471" height="343" alt="image" src="https://github.com/user-attachments/assets/053ec30d-0946-45b9-a186-f1c25106241c" />

<br>
<p>&nbsp;</p>

😺 7. 다음의 주소를 브라우저 창 주소에 복붙하세요

```text
http://127.0.0.1:8000
```

<br>
<p>&nbsp;</p>

# 사용 방법

<br>

😺 1. 접속하면 이런 페이지가 뜹니다. 음악 파일 선택하라는곳 클릭하여 노래를 업로드.
<br>

<img width="930" height="647" alt="image" src="https://github.com/user-attachments/assets/a0761d1d-09c2-4f43-bd9f-388f157ae5ba" />

<br>
<p>&nbsp;</p>

😺 2. 업로드 후 분리 시작 클릭! 하고 좀 기다리세요

<br>

<img width="800" height="464" alt="image" src="https://github.com/user-attachments/assets/97467169-bf85-46fd-b290-e8004e146b9a" />

<br>
<p>&nbsp;</p>

😺 3. 완료되면 이 페이지로 넘어가 지는데, 노브와 음소거 버튼을 잘 조절해서 원하는 악기의 소리를 강조하면 됩니다.

<br>

<img width="1280" height="938" alt="image" src="https://github.com/user-attachments/assets/3ce56a91-83f2-40be-a562-47089bdeeca2" />

<br>

<img width="1240" height="880" alt="image" src="https://github.com/user-attachments/assets/af498095-eb52-4d74-84f4-bc47c63ff512" />
<br>
(이런식으로)

<br>
<p>&nbsp;</p>

만족스러운 결과물이 나왔다면 위의 현재 믹스 다운로드를 클릭하여 음원을 다운합니다.

<br>
<p>&nbsp;</p>

# 잡담과 사용팁


구글링하면 나오는 사이트들 돈 내야 노래 풀로 변환 가능하던데(아님 말고), 괘씸해서 직접 코덱스로 짬.

기타 타브 귀카피는 좀 빡쌜거 같고(리듬기타랑 리드 기타 구분이 안되고 약간 물빠진 소리로 들리는데, 이건 어쩔 수 없는 부분), 베이스랑 기타는 하기 편할 거임.

❗⚠️악기 소리를 하나만 활성화 하면 음질이 물빠진 느낌이 날텐데, 다른 악기 볼륨을 약간 키워가면서 알맞게 조절하면 좀 나아질겁니다.

❗⚠️그리고 노브 조절하다보면 노래가 좀 이상하게 섞이게 되는데, 맨 위에 재생버튼 눌러서 일시정지 했다가 다시 재생하면 맞춰집니다.
노브 조절할 때마다 습관적으로 일시정지 했다가 재생하면 될 듯.

타브 악보도 추출하도록 하고 싶었는데 잘 안돼서 일단 비활성화 상태.

GPU 없어도 CPU만으로 되긴 하던데, 느리고 사양이 딸리면 안될 수 있음.

(램은 32gb 추천)

(라이젠7 9700X, RTX 5060 Ti 사용 중인데 GPU 사용하면 얼마 안 걸리고, CPU는 좀 걸렸음.)


Q. 노래 음원은 어디서 받아요?

A. 유튜브 링크 복사하면 mp3변환해주는 사이트들 많으니 그거 이용하면 됩니다. (추천하는 곳은 cnvmp3.com)


