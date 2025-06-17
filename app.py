import os
import hashlib
import datetime
from flask import Flask, render_template_string, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import PyPDF2
import docx
from sqlalchemy import or_, and_, func
import json

app = Flask(__name__)

# Configurações
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///tribunal.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Criar pasta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Modelos atualizados
class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    materias = db.relationship('Materia', backref='categoria', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome
        }

class Materia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), unique=True, nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria.id'), nullable=False)
    sentencas = db.relationship('Sentenca', backref='materia', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'categoria_id': self.categoria_id,
            'categoria_nome': self.categoria.nome
        }

class Sentenca(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero_processo = db.Column(db.String(50), nullable=False)
    data_sentenca = db.Column(db.Date, nullable=False)
    materia_id = db.Column(db.Integer, db.ForeignKey('materia.id'), nullable=False)
    resultado = db.Column(db.String(100), nullable=False)
    foi_corrigido = db.Column(db.Boolean, default=False)
    observacoes = db.Column(db.Text)
    conteudo = db.Column(db.Text)
    arquivo_nome = db.Column(db.String(200))
    arquivo_path = db.Column(db.String(500))
    hash_documento = db.Column(db.String(64))
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'numero_processo': self.numero_processo,
            'data_sentenca': self.data_sentenca.strftime('%d/%m/%Y'),
            'materia': self.materia.nome,
            'categoria': self.materia.categoria.nome,
            'resultado': self.resultado,
            'foi_corrigido': self.foi_corrigido,
            'observacoes': self.observacoes,
            'arquivo_nome': self.arquivo_nome,
            'criado_em': self.criado_em.strftime('%d/%m/%Y %H:%M')
        }

class TipoResultado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome
        }

# Template HTML atualizado
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistema de Sentenças - Tribunal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .autocomplete-dropdown {
            position: absolute;
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 0.375rem;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            max-height: 200px;
            overflow-y: auto;
            z-index: 50;
        }
        .autocomplete-item {
            padding: 0.5rem 1rem;
            cursor: pointer;
        }
        .autocomplete-item:hover {
            background-color: #f3f4f6;
        }
        .autocomplete-item.selected {
            background-color: #eff6ff;
        }
        .categoria-tag {
            font-size: 0.75rem;
            color: #6b7280;
        }
    </style>
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
                            <h1 class="text-2xl font-bold">Sistema de Sentenças</h1>
                            <p class="text-blue-200 text-sm">Gestão de Documentos Jurídicos</p>
                        </div>
                    </div>
                    <div class="flex items-center space-x-4">
                        <span class="text-sm">Total de sentenças: <span id="totalSentencas" class="font-bold">0</span></span>
                    </div>
                </div>
            </div>
        </header>

        <div class="container mx-auto px-4 py-8">
            <!-- Cadastro de Sentença -->
            <div class="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 class="text-xl font-semibold mb-4 flex items-center">
                    <i class="fas fa-gavel mr-2 text-blue-600"></i>
                    Cadastrar Nova Sentença
                </h2>
                
                <form id="sentencaForm" class="space-y-4">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <!-- Matéria com autocomplete -->
                        <div class="relative">
                            <label class="block text-sm font-medium mb-1">Matéria *</label>
                            <input type="text" id="materia" placeholder="Digite a matéria..." 
                                   class="w-full border rounded-lg px-3 py-2" required autocomplete="off">
                            <div id="materiaDropdown" class="autocomplete-dropdown hidden"></div>
                        </div>
                        
                        <!-- Categoria -->
                        <div>
                            <label class="block text-sm font-medium mb-1">Categoria *</label>
                            <select id="categoria" class="w-full border rounded-lg px-3 py-2" required>
                                <option value="">Selecione ou crie nova...</option>
                            </select>
                            <input type="text" id="novaCategoria" placeholder="Nova categoria..." 
                                   class="w-full border rounded-lg px-3 py-2 mt-2 hidden">
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <!-- Número do Processo -->
                        <div>
                            <label class="block text-sm font-medium mb-1">Número do Processo *</label>
                            <input type="text" id="processo" placeholder="0000000-00.0000.0.00.0000" 
                                   class="w-full border rounded-lg px-3 py-2" required>
                        </div>
                        
                        <!-- Data da Sentença -->
                        <div>
                            <label class="block text-sm font-medium mb-1">Data da Sentença *</label>
                            <input type="date" id="data" class="w-full border rounded-lg px-3 py-2" required>
                        </div>
                        
                        <!-- Resultado -->
                        <div>
                            <label class="block text-sm font-medium mb-1">Resultado *</label>
                            <select id="resultado" class="w-full border rounded-lg px-3 py-2" required>
                                <option value="">Selecione...</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <!-- Foi corrigido -->
                        <div>
                            <label class="block text-sm font-medium mb-1">Foi corrigido?</label>
                            <div class="flex items-center space-x-4 mt-2">
                                <label class="flex items-center">
                                    <input type="radio" name="corrigido" value="true" class="mr-2">
                                    <span>Sim</span>
                                </label>
                                <label class="flex items-center">
                                    <input type="radio" name="corrigido" value="false" class="mr-2" checked>
                                    <span>Não</span>
                                </label>
                            </div>
                        </div>
                        
                        <!-- Arquivo -->
                        <div>
                            <label class="block text-sm font-medium mb-1">Arquivo DOCX</label>
                            <div class="border-2 border-dashed border-gray-300 rounded-lg p-4 text-center">
                                <input type="file" id="arquivo" accept=".docx" class="hidden">
                                <i class="fas fa-file-word text-3xl text-gray-400 mb-2"></i>
                                <p class="text-gray-600 text-sm">Clique ou arraste o arquivo aqui</p>
                                <p id="fileName" class="text-sm text-blue-600 mt-2"></p>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Observações -->
                    <div>
                        <label class="block text-sm font-medium mb-1">Observações</label>
                        <textarea id="observacoes" rows="3" placeholder="Observações adicionais..." 
                                  class="w-full border rounded-lg px-3 py-2"></textarea>
                    </div>
                    
                    <button type="submit" class="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition">
                        <i class="fas fa-save mr-2"></i>Salvar Sentença
                    </button>
                </form>
            </div>

            <!-- Busca -->
            <div class="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 class="text-xl font-semibold mb-4 flex items-center">
                    <i class="fas fa-search mr-2 text-blue-600"></i>
                    Buscar Sentenças
                </h2>
                
                <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <input type="text" id="buscaTexto" placeholder="Buscar por processo, matéria..." 
                           class="border rounded-lg px-4 py-2">
                    <select id="buscaCategoria" class="border rounded-lg px-4 py-2">
                        <option value="">Todas as categorias</option>
                    </select>
                    <select id="buscaResultado" class="border rounded-lg px-4 py-2">
                        <option value="">Todos os resultados</option>
                    </select>
                    <button onclick="buscarSentencas()" class="bg-gray-600 text-white px-6 py-2 rounded-lg hover:bg-gray-700">
                        <i class="fas fa-search mr-2"></i>Buscar
                    </button>
                </div>
            </div>

            <!-- Resultados -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-semibold mb-4 flex items-center">
                    <i class="fas fa-folder-open mr-2 text-blue-600"></i>
                    Sentenças Cadastradas
                </h2>
                
                <div id="loading" class="text-center py-8 hidden">
                    <i class="fas fa-spinner fa-spin text-4xl text-blue-600"></i>
                    <p class="mt-2 text-gray-600">Carregando sentenças...</p>
                </div>
                
                <div id="sentencasList" class="space-y-4">
                    <!-- Sentenças serão inseridas aqui -->
                </div>
                
                <div id="emptyState" class="text-center py-8 text-gray-500">
                    <i class="fas fa-inbox text-5xl mb-3"></i>
                    <p>Nenhuma sentença encontrada</p>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal de Visualização -->
    <div id="viewModal" class="fixed inset-0 bg-black bg-opacity-50 hidden z-50">
        <div class="bg-white rounded-lg max-w-4xl mx-auto mt-10 p-6 max-h-screen overflow-y-auto">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-xl font-semibold">Detalhes da Sentença</h3>
                <button onclick="closeModal()" class="text-gray-500 hover:text-gray-700">
                    <i class="fas fa-times text-2xl"></i>
                </button>
            </div>
            <div id="modalContent" class="space-y-4">
                <!-- Conteúdo da sentença -->
            </div>
        </div>
    </div>

    <script>
        let materias = [];
        let categorias = [];
        let tiposResultado = [];
        let selectedMateriaIndex = -1;
        
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
        
        // Autocomplete de matéria
        const materiaInput = document.getElementById('materia');
        const materiaDropdown = document.getElementById('materiaDropdown');
        
        materiaInput.addEventListener('input', async (e) => {
            const valor = e.target.value.toLowerCase();
            if (valor.length < 2) {
                materiaDropdown.classList.add('hidden');
                return;
            }
            
            // Buscar matérias similares
            const response = await fetch(`/api/materias/buscar?q=${encodeURIComponent(valor)}`);
            const materiasSimilares = await response.json();
            
            if (materiasSimilares.length > 0) {
                materiaDropdown.innerHTML = materiasSimilares.map((m, index) => `
                    <div class="autocomplete-item ${index === selectedMateriaIndex ? 'selected' : ''}" 
                         data-id="${m.id}" data-categoria-id="${m.categoria_id}" data-index="${index}">
                        <div>${m.nome}</div>
                        <div class="categoria-tag">Categoria: ${m.categoria_nome}</div>
                    </div>
                `).join('');
                
                materiaDropdown.classList.remove('hidden');
                
                // Adicionar event listeners
                document.querySelectorAll('.autocomplete-item').forEach(item => {
                    item.addEventListener('click', () => {
                        materiaInput.value = item.querySelector('div').textContent;
                        document.getElementById('categoria').value = item.dataset.categoriaId;
                        materiaDropdown.classList.add('hidden');
                        selectedMateriaIndex = -1;
                    });
                });
            } else {
                materiaDropdown.classList.add('hidden');
            }
        });
        
        // Navegação com teclado no autocomplete
        materiaInput.addEventListener('keydown', (e) => {
            const items = document.querySelectorAll('.autocomplete-item');
            if (items.length === 0) return;
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedMateriaIndex = Math.min(selectedMateriaIndex + 1, items.length - 1);
                updateSelectedItem(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedMateriaIndex = Math.max(selectedMateriaIndex - 1, -1);
                updateSelectedItem(items);
            } else if (e.key === 'Enter' && selectedMateriaIndex >= 0) {
                e.preventDefault();
                items[selectedMateriaIndex].click();
            }
        });
        
        function updateSelectedItem(items) {
            items.forEach((item, index) => {
                if (index === selectedMateriaIndex) {
                    item.classList.add('selected');
                } else {
                    item.classList.remove('selected');
                }
            });
        }
        
        // Fechar dropdown ao clicar fora
        document.addEventListener('click', (e) => {
            if (!materiaInput.contains(e.target) && !materiaDropdown.contains(e.target)) {
                materiaDropdown.classList.add('hidden');
                selectedMateriaIndex = -1;
            }
        });
        
        // Categoria
        const categoriaSelect = document.getElementById('categoria');
        const novaCategoriaInput = document.getElementById('novaCategoria');
        
        categoriaSelect.addEventListener('change', (e) => {
            if (e.target.value === 'nova') {
                novaCategoriaInput.classList.remove('hidden');
                novaCategoriaInput.required = true;
            } else {
                novaCategoriaInput.classList.add('hidden');
                novaCategoriaInput.required = false;
                novaCategoriaInput.value = '';
            }
        });
        
        // Submissão do formulário
        document.getElementById('sentencaForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = new FormData();
            
            // Criar matéria/categoria se necessário
            let materiaId;
            const materiaTexto = document.getElementById('materia').value;
            const categoriaId = document.getElementById('categoria').value;
            
            if (categoriaId === 'nova') {
                // Criar nova categoria
                const novaCategoria = document.getElementById('novaCategoria').value;
                const catResponse = await fetch('/api/categorias', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nome: novaCategoria })
                });
                const catData = await catResponse.json();
                materiaId = await criarMateria(materiaTexto, catData.id);
            } else if (categoriaId) {
                // Verificar se a matéria já existe ou criar nova
                const materiaExistente = materias.find(m => 
                    m.nome.toLowerCase() === materiaTexto.toLowerCase()
                );
                
                if (materiaExistente) {
                    materiaId = materiaExistente.id;
                } else {
                    materiaId = await criarMateria(materiaTexto, categoriaId);
                }
            }
            
            formData.append('materia_id', materiaId);
            formData.append('processo', document.getElementById('processo').value);
            formData.append('data', document.getElementById('data').value);
            formData.append('resultado', document.getElementById('resultado').value);
            formData.append('foi_corrigido', document.querySelector('input[name="corrigido"]:checked').value);
            formData.append('observacoes', document.getElementById('observacoes').value);
            
            if (fileInput.files[0]) {
                formData.append('arquivo', fileInput.files[0]);
            }
            
            try {
                const response = await fetch('/api/sentencas', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('Sentença cadastrada com sucesso!');
                    document.getElementById('sentencaForm').reset();
                    document.getElementById('fileName').textContent = '';
                    carregarDados();
                    buscarSentencas();
                } else {
                    alert('Erro: ' + result.error);
                }
            } catch (error) {
                alert('Erro ao salvar sentença');
            }
        });
        
        async function criarMateria(nome, categoriaId) {
            const response = await fetch('/api/materias', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome, categoria_id: categoriaId })
            });
            const data = await response.json();
            return data.id;
        }
        
        // Buscar sentenças
        async function buscarSentencas() {
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('sentencasList').innerHTML = '';
            document.getElementById('emptyState').classList.add('hidden');
            
            try {
                const params = new URLSearchParams();
                const texto = document.getElementById('buscaTexto').value;
                const categoria = document.getElementById('buscaCategoria').value;
                const resultado = document.getElementById('buscaResultado').value;
                
                if (texto) params.append('q', texto);
                if (categoria) params.append('categoria', categoria);
                if (resultado) params.append('resultado', resultado);
                
                const response = await fetch('/api/sentencas?' + params);
                const sentencas = await response.json();
                
                document.getElementById('loading').classList.add('hidden');
                
                if (sentencas.length === 0) {
                    document.getElementById('emptyState').classList.remove('hidden');
                } else {
                    sentencas.forEach(sentenca => {
                        const corrigidoIcon = sentenca.foi_corrigido 
                            ? '<i class="fas fa-check-circle text-green-600" title="Corrigido"></i>'
                            : '<i class="fas fa-times-circle text-red-600" title="Não corrigido"></i>';
                        
                        const sentencaHtml = `
                            <div class="border rounded-lg p-4 hover:shadow-md transition">
                                <div class="flex justify-between items-start">
                                    <div class="flex-1">
                                        <div class="flex items-center gap-3 mb-2">
                                            <span class="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                                                ${sentenca.categoria}
                                            </span>
                                            <span class="bg-gray-100 text-gray-800 text-xs px-2 py-1 rounded">
                                                ${sentenca.resultado}
                                            </span>
                                            ${corrigidoIcon}
                                            <span class="text-gray-600 text-sm">${sentenca.numero_processo}</span>
                                            <span class="text-gray-500 text-sm">${sentenca.data_sentenca}</span>
                                        </div>
                                        <h3 class="font-semibold mb-1">${sentenca.materia}</h3>
                                        ${sentenca.observacoes ? `<p class="text-gray-600 text-sm">${sentenca.observacoes}</p>` : ''}
                                    </div>
                                    <div class="flex gap-2 ml-4">
                                        <button onclick="visualizarSentenca(${sentenca.id})" 
                                                class="text-blue-600 hover:text-blue-800">
                                            <i class="fas fa-eye"></i>
                                        </button>
                                        ${sentenca.arquivo_nome ? `
                                            <button onclick="baixarDocumento(${sentenca.id})" 
                                                    class="text-green-600 hover:text-green-800">
                                                <i class="fas fa-download"></i>
                                            </button>
                                        ` : ''}
                                    </div>
                                </div>
                            </div>
                        `;
                        document.getElementById('sentencasList').innerHTML += sentencaHtml;
                    });
                }
                
                document.getElementById('totalSentencas').textContent = sentencas.length;
            } catch (error) {
                document.getElementById('loading').classList.add('hidden');
                alert('Erro ao buscar sentenças');
            }
        }
        
        // Visualizar sentença
        async function visualizarSentenca(id) {
            try {
                const response = await fetch(`/api/sentencas/${id}`);
                const sentenca = await response.json();
                
                const corrigidoTexto = sentenca.foi_corrigido ? 'Sim' : 'Não';
                
                document.getElementById('modalContent').innerHTML = `
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <p class="text-sm text-gray-600">Processo</p>
                            <p class="font-semibold">${sentenca.numero_processo}</p>
                        </div>
                        <div>
                            <p class="text-sm text-gray-600">Data da Sentença</p>
                            <p class="font-semibold">${sentenca.data_sentenca}</p>
                        </div>
                        <div>
                            <p class="text-sm text-gray-600">Matéria</p>
                            <p class="font-semibold">${sentenca.materia}</p>
                        </div>
                        <div>
                            <p class="text-sm text-gray-600">Categoria</p>
                            <p class="font-semibold">${sentenca.categoria}</p>
                        </div>
                        <div>
                            <p class="text-sm text-gray-600">Resultado</p>
                            <p class="font-semibold">${sentenca.resultado}</p>
                        </div>
                        <div>
                            <p class="text-sm text-gray-600">Foi Corrigido?</p>
                            <p class="font-semibold">${corrigidoTexto}</p>
                        </div>
                    </div>
                    ${sentenca.observacoes ? `
                        <div class="mt-4">
                            <p class="text-sm text-gray-600">Observações</p>
                            <p class="font-semibold">${sentenca.observacoes}</p>
                        </div>
                    ` : ''}
                    ${sentenca.conteudo ? `
                        <div class="mt-4 border-t pt-4">
                            <p class="text-sm text-gray-600 mb-2">Conteúdo do Documento</p>
                            <div class="bg-gray-50 p-4 rounded max-h-96 overflow-y-auto">
                                <pre class="whitespace-pre-wrap text-sm">${sentenca.conteudo}</pre>
                            </div>
                        </div>
                    ` : ''}
                `;
                
                document.getElementById('viewModal').classList.remove('hidden');
            } catch (error) {
                alert('Erro ao visualizar sentença');
            }
        }
        
        // Baixar documento
        function baixarDocumento(id) {
            window.open(`/api/sentencas/${id}/download`, '_blank');
        }
        
        // Fechar modal
        function closeModal() {
            document.getElementById('viewModal').classList.add('hidden');
        }
        
        // Carregar dados iniciais
        async function carregarDados() {
            // Carregar categorias
            const catResponse = await fetch('/api/categorias');
            categorias = await catResponse.json();
            
            const categoriaSelect = document.getElementById('categoria');
            const buscaCategoriaSelect = document.getElementById('buscaCategoria');
            
            categoriaSelect.innerHTML = '<option value="">Selecione...</option>';
            buscaCategoriaSelect.innerHTML = '<option value="">Todas as categorias</option>';
            
            categorias.forEach(cat => {
                categoriaSelect.innerHTML += `<option value="${cat.id}">${cat.nome}</option>`;
                buscaCategoriaSelect.innerHTML += `<option value="${cat.id}">${cat.nome}</option>`;
            });
            
            categoriaSelect.innerHTML += '<option value="nova">+ Nova categoria</option>';
            
            // Carregar tipos de resultado
            const resultResponse = await fetch('/api/tipos-resultado');
            tiposResultado = await resultResponse.json();
            
            const resultadoSelect = document.getElementById('resultado');
            const buscaResultadoSelect = document.getElementById('buscaResultado');
            
            resultadoSelect.innerHTML = '<option value="">Selecione...</option>';
            buscaResultadoSelect.innerHTML = '<option value="">Todos os resultados</option>';
            
            tiposResultado.forEach(tipo => {
                resultadoSelect.innerHTML += `<option value="${tipo.nome}">${tipo.nome}</option>`;
                buscaResultadoSelect.innerHTML += `<option value="${tipo.nome}">${tipo.nome}</option>`;
            });
            
            // Carregar matérias
            const matResponse = await fetch('/api/materias');
            materias = await matResponse.json();
        }
        
        // Inicializar
        carregarDados();
        buscarSentencas();
    </script>
</body>
</html>
'''

# Rotas da API
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# Categorias
@app.route('/api/categorias', methods=['GET'])
def listar_categorias():
    categorias = Categoria.query.order_by(Categoria.nome).all()
    return jsonify([cat.to_dict() for cat in categorias])

@app.route('/api/categorias', methods=['POST'])
def criar_categoria():
    try:
        data = request.json
        nova_categoria = Categoria(nome=data['nome'])
        db.session.add(nova_categoria)
        db.session.commit()
        return jsonify({'success': True, 'id': nova_categoria.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Matérias
@app.route('/api/materias', methods=['GET'])
def listar_materias():
    materias = Materia.query.all()
    return jsonify([mat.to_dict() for mat in materias])

@app.route('/api/materias', methods=['POST'])
def criar_materia():
    try:
        data = request.json
        nova_materia = Materia(
            nome=data['nome'],
            categoria_id=data['categoria_id']
        )
        db.session.add(nova_materia)
        db.session.commit()
        return jsonify({'success': True, 'id': nova_materia.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/materias/buscar')
def buscar_materias():
    query = request.args.get('q', '').lower()
    if len(query) < 2:
        return jsonify([])
    
    # Buscar matérias que contenham o texto
    materias = Materia.query.filter(
        Materia.nome.ilike(f'%{query}%')
    ).limit(10).all()
    
    # Também buscar variações (ex: "bacem SCR" encontra "SCR bacem")
    palavras = query.split()
    if len(palavras) > 1:
        # Buscar com palavras em qualquer ordem
        for palavra in palavras:
            materias_extra = Materia.query.filter(
                Materia.nome.ilike(f'%{palavra}%')
            ).limit(5).all()
            for mat in materias_extra:
                if mat not in materias:
                    materias.append(mat)
    
    return jsonify([mat.to_dict() for mat in materias[:10]])

# Tipos de Resultado
@app.route('/api/tipos-resultado', methods=['GET'])
def listar_tipos_resultado():
    tipos = TipoResultado.query.all()
    return jsonify([tipo.to_dict() for tipo in tipos])

# Sentenças
@app.route('/api/sentencas', methods=['GET'])
def listar_sentencas():
    try:
        query_text = request.args.get('q', '')
        categoria_id = request.args.get('categoria', '')
        resultado = request.args.get('resultado', '')
        
        # Construir query
        sentencas_query = Sentenca.query.join(Materia).join(Categoria)
        
        if query_text:
            search_filter = or_(
                Sentenca.numero_processo.contains(query_text),
                Materia.nome.contains(query_text),
                Sentenca.observacoes.contains(query_text)
            )
            sentencas_query = sentencas_query.filter(search_filter)
        
        if categoria_id:
            sentencas_query = sentencas_query.filter(Categoria.id == categoria_id)
        
        if resultado:
            sentencas_query = sentencas_query.filter(Sentenca.resultado == resultado)
        
        # Ordenar por data decrescente
        sentencas = sentencas_query.order_by(Sentenca.data_sentenca.desc()).all()
        
        return jsonify([sent.to_dict() for sent in sentencas])
    except Exception as e:
        return jsonify([])

@app.route('/api/sentencas', methods=['POST'])
def criar_sentenca():
    try:
        # Processar arquivo se enviado
        conteudo = ''
        arquivo_nome = None
        arquivo_path = None
        hash_doc = None
        
        if 'arquivo' in request.files:
            file = request.files['arquivo']
            if file and file.filename.endswith('.docx'):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                # Extrair texto do DOCX
                doc = docx.Document(filepath)
                conteudo = '\n'.join([p.text for p in doc.paragraphs])
                
                # Calcular hash
                with open(filepath, 'rb') as f:
                    hash_doc = hashlib.sha256(f.read()).hexdigest()
                
                arquivo_nome = filename
                arquivo_path = filepath
        
        # Criar sentença
        nova_sentenca = Sentenca(
            numero_processo=request.form.get('processo'),
            data_sentenca=datetime.datetime.strptime(request.form.get('data'), '%Y-%m-%d').date(),
            materia_id=int(request.form.get('materia_id')),
            resultado=request.form.get('resultado'),
            foi_corrigido=request.form.get('foi_corrigido') == 'true',
            observacoes=request.form.get('observacoes', ''),
            conteudo=conteudo,
            arquivo_nome=arquivo_nome,
            arquivo_path=arquivo_path,
            hash_documento=hash_doc
        )
        
        db.session.add(nova_sentenca)
        db.session.commit()
        
        return jsonify({'success': True, 'id': nova_sentenca.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/sentencas/<int:id>')
def ver_sentenca(id):
    try:
        sentenca = Sentenca.query.get_or_404(id)
        return jsonify({
            'id': sentenca.id,
            'numero_processo': sentenca.numero_processo,
            'data_sentenca': sentenca.data_sentenca.strftime('%d/%m/%Y'),
            'materia': sentenca.materia.nome,
            'categoria': sentenca.materia.categoria.nome,
            'resultado': sentenca.resultado,
            'foi_corrigido': sentenca.foi_corrigido,
            'observacoes': sentenca.observacoes,
            'conteudo': sentenca.conteudo,
            'arquivo_nome': sentenca.arquivo_nome
        })
    except Exception as e:
        return jsonify({'error': 'Sentença não encontrada'}), 404

@app.route('/api/sentencas/<int:id>/download')
def download_sentenca(id):
    try:
        sentenca = Sentenca.query.get_or_404(id)
        if sentenca.arquivo_path and os.path.exists(sentenca.arquivo_path):
            return send_file(sentenca.arquivo_path, as_attachment=True, download_name=sentenca.arquivo_nome)
        else:
            return jsonify({'error': 'Arquivo não encontrado'}), 404
    except Exception as e:
        return jsonify({'error': 'Erro ao baixar arquivo'}), 500

# Inicializar banco de dados e dados padrão
def init_db():
    with app.app_context():
        db.create_all()
        
        # Criar categorias padrão se não existirem
        categorias_padrao = [
            'Saúde', 'Crédito', 'Ação de cobrança', 'Busca e apreensão',
            'Educação', 'Inexistência de débito', 'Aéreo', 'Refaturamentos',
            'Revisionais de contratos', 'Falha na prestação de serviços', 'Seguros'
        ]
        
        for cat_nome in categorias_padrao:
            if not Categoria.query.filter_by(nome=cat_nome).first():
                cat = Categoria(nome=cat_nome)
                db.session.add(cat)
        
        # Criar tipos de resultado padrão
        tipos_resultado_padrao = [
            'Procedente', 'Improcedente', 'Procedente em parte',
            'Litis pendência / Coisa julgada', 'Convertido em diligência',
            'Incompetência'
        ]
        
        for tipo_nome in tipos_resultado_padrao:
            if not TipoResultado.query.filter_by(nome=tipo_nome).first():
                tipo = TipoResultado(nome=tipo_nome)
                db.session.add(tipo)
        
        db.session.commit()

# Executar inicialização
init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
