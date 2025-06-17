import os
import hashlib
import datetime
from flask import Flask, render_template_string, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import PyPDF2
import docx
from sqlalchemy import or_, and_
import json

app = Flask(__name__)

# Configurações
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///tribunal.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Criar pasta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Modelos
class Documento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    numero_processo = db.Column(db.String(50), nullable=False)
    data_documento = db.Column(db.Date, nullable=False)
    titulo = db.Column(db.String(200))
    conteudo = db.Column(db.Text)
    arquivo_nome = db.Column(db.String(200))
    arquivo_path = db.Column(db.String(500))
    hash_documento = db.Column(db.String(64))
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'tipo': self.tipo,
            'numero_processo': self.numero_processo,
            'data_documento': self.data_documento.strftime('%d/%m/%Y'),
            'titulo': self.titulo,
            'conteudo': self.conteudo[:200] + '...' if self.conteudo else '',
            'arquivo_nome': self.arquivo_nome,
            'criado_em': self.criado_em.strftime('%d/%m/%Y %H:%M')
        }

# Template HTML (interface completa)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistema de Acervo Digital - Tribunal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-gray-50">
    <div class="min-h-screen">
        <!-- Header -->
        <header class="bg-blue-900 text-white shadow-lg">
            <div class="container mx-auto px-4 py-4">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-4">
                        <i class="fas fa-balance-scale text-3xl"></i>
                        <div>
                            <h1 class="text-2xl font-bold">Acervo Digital</h1>
                            <p class="text-blue-200 text-sm">Sistema de Gestão de Documentos Jurídicos</p>
                        </div>
                    </div>
                    <div class="flex items-center space-x-4">
                        <span class="text-sm">Total de documentos: <span id="totalDocs" class="font-bold">0</span></span>
                    </div>
                </div>
            </div>
        </header>

        <div class="container mx-auto px-4 py-8">
            <!-- Upload Section -->
            <div class="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 class="text-xl font-semibold mb-4 flex items-center">
                    <i class="fas fa-upload mr-2 text-blue-600"></i>
                    Adicionar Novo Documento
                </h2>
                
                <form id="uploadForm" class="space-y-4">
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                            <label class="block text-sm font-medium mb-1">Tipo de Documento</label>
                            <select id="tipo" class="w-full border rounded-lg px-3 py-2" required>
                                <option value="">Selecione...</option>
                                <option value="sentenca">Sentença</option>
                                <option value="decisao">Decisão</option>
                                <option value="despacho">Despacho</option>
                                <option value="peticao">Petição</option>
                                <option value="parecer">Parecer</option>
                            </select>
                        </div>
                        
                        <div>
                            <label class="block text-sm font-medium mb-1">Número do Processo</label>
                            <input type="text" id="processo" placeholder="0000000-00.0000.0.00.0000" 
                                   class="w-full border rounded-lg px-3 py-2" required>
                        </div>
                        
                        <div>
                            <label class="block text-sm font-medium mb-1">Data do Documento</label>
                            <input type="date" id="data" class="w-full border rounded-lg px-3 py-2" required>
                        </div>
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium mb-1">Título/Descrição</label>
                        <input type="text" id="titulo" placeholder="Ex: Sentença de procedência parcial" 
                               class="w-full border rounded-lg px-3 py-2">
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium mb-1">Arquivo (PDF ou DOCX)</label>
                        <div class="border-2 border-dashed border-gray-300 rounded-lg p-4 text-center">
                            <input type="file" id="arquivo" accept=".pdf,.docx" class="hidden">
                            <i class="fas fa-cloud-upload-alt text-4xl text-gray-400 mb-2"></i>
                            <p class="text-gray-600">Clique ou arraste o arquivo aqui</p>
                            <p class="text-sm text-gray-500 mt-1">Máximo: 16MB</p>
                            <p id="fileName" class="text-sm text-blue-600 mt-2"></p>
                        </div>
                    </div>
                    
                    <button type="submit" class="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition">
                        <i class="fas fa-save mr-2"></i>Salvar Documento
                    </button>
                </form>
            </div>

            <!-- Search Section -->
            <div class="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 class="text-xl font-semibold mb-4 flex items-center">
                    <i class="fas fa-search mr-2 text-blue-600"></i>
                    Buscar Documentos
                </h2>
                
                <div class="flex gap-4">
                    <input type="text" id="searchInput" placeholder="Buscar por processo, título ou conteúdo..." 
                           class="flex-1 border rounded-lg px-4 py-2">
                    <select id="filterTipo" class="border rounded-lg px-4 py-2">
                        <option value="">Todos os tipos</option>
                        <option value="sentenca">Sentenças</option>
                        <option value="decisao">Decisões</option>
                        <option value="despacho">Despachos</option>
                        <option value="peticao">Petições</option>
                        <option value="parecer">Pareceres</option>
                    </select>
                    <button onclick="buscarDocumentos()" class="bg-gray-600 text-white px-6 py-2 rounded-lg hover:bg-gray-700">
                        <i class="fas fa-search mr-2"></i>Buscar
                    </button>
                </div>
            </div>

            <!-- Results Section -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-semibold mb-4 flex items-center">
                    <i class="fas fa-folder-open mr-2 text-blue-600"></i>
                    Documentos Encontrados
                </h2>
                
                <div id="loading" class="text-center py-8 hidden">
                    <i class="fas fa-spinner fa-spin text-4xl text-blue-600"></i>
                    <p class="mt-2 text-gray-600">Carregando documentos...</p>
                </div>
                
                <div id="documentList" class="space-y-4">
                    <!-- Documentos serão inseridos aqui -->
                </div>
                
                <div id="emptyState" class="text-center py-8 text-gray-500">
                    <i class="fas fa-inbox text-5xl mb-3"></i>
                    <p>Nenhum documento encontrado</p>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal de Visualização -->
    <div id="viewModal" class="fixed inset-0 bg-black bg-opacity-50 hidden z-50">
        <div class="bg-white rounded-lg max-w-4xl mx-auto mt-10 p-6 max-h-screen overflow-y-auto">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-xl font-semibold">Visualizar Documento</h3>
                <button onclick="closeModal()" class="text-gray-500 hover:text-gray-700">
                    <i class="fas fa-times text-2xl"></i>
                </button>
            </div>
            <div id="modalContent" class="prose max-w-none">
                <!-- Conteúdo do documento -->
            </div>
        </div>
    </div>

    <script>
        // Configurar área de upload
        const fileInput = document.getElementById('arquivo');
        const dropZone = fileInput.parentElement;
        
        dropZone.addEventListener('click', () => fileInput.click());
        
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                document.getElementById('fileName').textContent = file.name;
            }
        });
        
        // Prevenir comportamento padrão de arrastar
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('border-blue-500', 'bg-blue-50');
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('border-blue-500', 'bg-blue-50');
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('border-blue-500', 'bg-blue-50');
            
            const file = e.dataTransfer.files[0];
            if (file && (file.type === 'application/pdf' || file.name.endsWith('.docx'))) {
                fileInput.files = e.dataTransfer.files;
                document.getElementById('fileName').textContent = file.name;
            }
        });
        
        // Upload de documento
        document.getElementById('uploadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = new FormData();
            formData.append('tipo', document.getElementById('tipo').value);
            formData.append('processo', document.getElementById('processo').value);
            formData.append('data', document.getElementById('data').value);
            formData.append('titulo', document.getElementById('titulo').value);
            formData.append('arquivo', fileInput.files[0]);
            
            try {
                const response = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('Documento salvo com sucesso!');
                    document.getElementById('uploadForm').reset();
                    document.getElementById('fileName').textContent = '';
                    carregarDocumentos();
                } else {
                    alert('Erro: ' + result.error);
                }
            } catch (error) {
                alert('Erro ao fazer upload');
            }
        });
        
        // Buscar documentos
        async function buscarDocumentos() {
            const query = document.getElementById('searchInput').value;
            const tipo = document.getElementById('filterTipo').value;
            
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('documentList').innerHTML = '';
            document.getElementById('emptyState').classList.add('hidden');
            
            try {
                const params = new URLSearchParams();
                if (query) params.append('q', query);
                if (tipo) params.append('tipo', tipo);
                
                const response = await fetch('/api/documentos?' + params);
                const documentos = await response.json();
                
                document.getElementById('loading').classList.add('hidden');
                
                if (documentos.length === 0) {
                    document.getElementById('emptyState').classList.remove('hidden');
                } else {
                    documentos.forEach(doc => {
                        const docHtml = `
                            <div class="border rounded-lg p-4 hover:shadow-md transition">
                                <div class="flex justify-between items-start">
                                    <div class="flex-1">
                                        <div class="flex items-center gap-3 mb-2">
                                            <span class="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                                                ${doc.tipo.toUpperCase()}
                                            </span>
                                            <span class="text-gray-600 text-sm">${doc.numero_processo}</span>
                                            <span class="text-gray-500 text-sm">${doc.data_documento}</span>
                                        </div>
                                        <h3 class="font-semibold mb-1">${doc.titulo || 'Sem título'}</h3>
                                        <p class="text-gray-600 text-sm">${doc.conteudo}</p>
                                    </div>
                                    <div class="flex gap-2 ml-4">
                                        <button onclick="visualizarDocumento(${doc.id})" 
                                                class="text-blue-600 hover:text-blue-800">
                                            <i class="fas fa-eye"></i>
                                        </button>
                                        <button onclick="baixarDocumento(${doc.id})" 
                                                class="text-green-600 hover:text-green-800">
                                            <i class="fas fa-download"></i>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        `;
                        document.getElementById('documentList').innerHTML += docHtml;
                    });
                }
                
                document.getElementById('totalDocs').textContent = documentos.length;
            } catch (error) {
                document.getElementById('loading').classList.add('hidden');
                alert('Erro ao buscar documentos');
            }
        }
        
        // Visualizar documento
        async function visualizarDocumento(id) {
            try {
                const response = await fetch(`/api/documento/${id}`);
                const doc = await response.json();
                
                document.getElementById('modalContent').innerHTML = `
                    <div class="mb-4">
                        <p><strong>Tipo:</strong> ${doc.tipo}</p>
                        <p><strong>Processo:</strong> ${doc.numero_processo}</p>
                        <p><strong>Data:</strong> ${doc.data_documento}</p>
                        <p><strong>Título:</strong> ${doc.titulo || 'Sem título'}</p>
                    </div>
                    <div class="border-t pt-4">
                        <h4 class="font-semibold mb-2">Conteúdo:</h4>
                        <div class="whitespace-pre-wrap">${doc.conteudo || 'Conteúdo não disponível'}</div>
                    </div>
                `;
                
                document.getElementById('viewModal').classList.remove('hidden');
            } catch (error) {
                alert('Erro ao visualizar documento');
            }
        }
        
        // Baixar documento
        function baixarDocumento(id) {
            window.open(`/api/download/${id}`, '_blank');
        }
        
        // Fechar modal
        function closeModal() {
            document.getElementById('viewModal').classList.add('hidden');
        }
        
        // Carregar documentos ao iniciar
        async function carregarDocumentos() {
            await buscarDocumentos();
        }
        
        // Carregar ao iniciar a página
        carregarDocumentos();
    </script>
</body>
</html>
'''

# Rotas
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/upload', methods=['POST'])
def upload():
    try:
        # Validar campos obrigatórios
        tipo = request.form.get('tipo')
        processo = request.form.get('processo')
        data = request.form.get('data')
        titulo = request.form.get('titulo', '')
        
        if not all([tipo, processo, data]):
            return jsonify({'success': False, 'error': 'Campos obrigatórios faltando'})
        
        # Processar arquivo
        file = request.files.get('arquivo')
        if not file:
            return jsonify({'success': False, 'error': 'Arquivo não enviado'})
        
        # Salvar arquivo
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Extrair texto do arquivo
        conteudo = ''
        if filename.lower().endswith('.pdf'):
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    conteudo += page.extract_text() + '\n'
        elif filename.lower().endswith('.docx'):
            doc = docx.Document(filepath)
            conteudo = '\n'.join([p.text for p in doc.paragraphs])
        
        # Calcular hash do documento
        with open(filepath, 'rb') as f:
            hash_doc = hashlib.sha256(f.read()).hexdigest()
        
        # Verificar duplicata
        existe = Documento.query.filter_by(hash_documento=hash_doc).first()
        if existe:
            return jsonify({'success': False, 'error': 'Documento já existe no sistema'})
        
        # Salvar no banco
        novo_doc = Documento(
            tipo=tipo,
            numero_processo=processo,
            data_documento=datetime.datetime.strptime(data, '%Y-%m-%d').date(),
            titulo=titulo,
            conteudo=conteudo,
            arquivo_nome=filename,
            arquivo_path=filepath,
            hash_documento=hash_doc
        )
        
        db.session.add(novo_doc)
        db.session.commit()
        
        return jsonify({'success': True, 'id': novo_doc.id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/documentos')
def listar_documentos():
    try:
        query = request.args.get('q', '')
        tipo = request.args.get('tipo', '')
        
        # Construir query
        documentos_query = Documento.query
        
        if tipo:
            documentos_query = documentos_query.filter_by(tipo=tipo)
        
        if query:
            search_filter = or_(
                Documento.numero_processo.contains(query),
                Documento.titulo.contains(query),
                Documento.conteudo.contains(query)
            )
            documentos_query = documentos_query.filter(search_filter)
        
        # Ordenar por data decrescente
        documentos = documentos_query.order_by(Documento.data_documento.desc()).all()
        
        return jsonify([doc.to_dict() for doc in documentos])
        
    except Exception as e:
        return jsonify([])

@app.route('/api/documento/<int:id>')
def ver_documento(id):
    try:
        doc = Documento.query.get_or_404(id)
        return jsonify({
            'id': doc.id,
            'tipo': doc.tipo,
            'numero_processo': doc.numero_processo,
            'data_documento': doc.data_documento.strftime('%d/%m/%Y'),
            'titulo': doc.titulo,
            'conteudo': doc.conteudo,
            'arquivo_nome': doc.arquivo_nome
        })
    except Exception as e:
        return jsonify({'error': 'Documento não encontrado'}), 404

@app.route('/api/download/<int:id>')
def download_documento(id):
    try:
        doc = Documento.query.get_or_404(id)
        if doc.arquivo_path and os.path.exists(doc.arquivo_path):
            return send_file(doc.arquivo_path, as_attachment=True, download_name=doc.arquivo_nome)
        else:
            return jsonify({'error': 'Arquivo não encontrado'}), 404
    except Exception as e:
        return jsonify({'error': 'Erro ao baixar arquivo'}), 500

# Criar tabelas
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
