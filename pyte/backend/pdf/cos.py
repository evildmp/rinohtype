
from collections import OrderedDict
from io import BytesIO, SEEK_END



PDF_VERSION = '1.4'


# TODO: encoding
# TODO: max line length (not streams)


class Object(object):
    def __init__(self, document=None):
        self.generation = 0
        self.document = document
        if document:
            self.identifier = document.next_identifier
            document.append(self)
            self.reference = Reference(document, self.identifier,
                                       self.generation)
        else:
            self.identifier = None

    @property
    def is_direct(self):
        return self.identifier is None

    def bytes(self):
        if self.is_direct:
            out = self._bytes()
        else:
            out = self.reference.bytes()
        return out

    def indirect_bytes(self):
        out = '{} {} obj\n'.format(self.identifier,
                                   self.generation).encode('utf_8')
        out += self._bytes()
        out += b'\nendobj'
        return out


# TODO: forward method calls to referred object (metaclass?)
class Reference(object):
    def __init__(self, document, identifier, generation):
        self.document = document
        self.identifier = identifier
        self.generation = generation

    def bytes(self):
        return '{} {} R'.format(self.identifier,
                                self.generation).encode('utf_8')

    @property
    def target(self):
        try:
            return self.document.get_indirect_object(self.identifier,
                                                     self.generation)
        except Exception as e:
            pass

    def __repr__(self):
        return '{}<{} {}>'.format(self.target.__class__.__name__,
                                  self.identifier, self.generation)

    def __getitem__(self, name):
        return self.target[name]

    def __getattr__(self, name):
        return getattr(self.target, name)


class Boolean(Object):
    def __init__(self, value, document=None):
        super().__init__(document)
        self.value = value

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.value)

    def _bytes(self):
        return b'true' if self.value else b'false'


class Integer(Object, int):
    def __init__(self, value, base=10, document=None):
        Object.__init__(self, document)

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, int.__repr__(self))

    def _bytes(self):
        return int.__str__(self).encode('utf_8')


class Real(Object, float):
    def __init__(self, value, document=None):
        Object.__init__(self, document)

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, float.__repr__(self))

    def _bytes(self):
        return float.__str__(self).encode('utf_8')


class String(Object):
    def __init__(self, string, document=None):
        super().__init__(document)
        self.value = string

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.value)

    def _bytes(self):
        escaped = self.value.replace('\n', r'\n')
        escaped = escaped.replace('\r', r'\r')
        escaped = escaped.replace('\t', r'\t')
        escaped = escaped.replace('\b', r'\b')
        escaped = escaped.replace('\f', r'\f')
        for char in '\\()':
            escaped = escaped.replace(char, '\\{}'.format(char))
        return '({})'.format(escaped).encode('utf_8')


class Name(Object):
    # TODO: names should be unique, check
    def __init__(self, name, document=None):
        super().__init__(document)
        self.name = name

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.name)

    def _bytes(self):
        # TODO: # escaping
        return '/{}'.format(self.name).encode('utf_8')


class Array(Object, list):
    def __init__(self, items=[], document=None):
        Object.__init__(self, document)
        list.__init__(self, items)

    def __repr__(self):
        return '{}{}'.format(self.__class__.__name__, list.__repr__(self))

    def _bytes(self):
        return b'[' + (b' '.join([elem.bytes() for elem in self])) + b']'


class Dictionary(Object, OrderedDict):
    def __init__(self, document=None):
        Object.__init__(self, document)
        OrderedDict.__init__(self)

    def __repr__(self):
        return '{}{}'.format(self.__class__.__name__, dict.__repr__(self))

    def _bytes(self):
        return b'<< ' + b' '.join([Name(key).bytes() + b' ' + value.bytes()
                                   for key, value in self.items()]) + b' >>'


class Stream(Object, BytesIO):
    def __init__(self, document):
        Object.__init__(self, document)
        BytesIO.__init__(self)

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.size)

    def _bytes(self):
        dictionary = Dictionary()
        dictionary['Length'] = Integer(self.size)
        out = dictionary.bytes()
        out += b'\nstream\n'
        out += self.getvalue()
        out += b'\nendstream'
        return out

    @property
    def size(self):
        restore_pos = self.tell()
        self.seek(0, SEEK_END)
        size = self.tell()
        self.seek(restore_pos)
        return size


class Null(Object):
    def __init__(self):
        pass

    def __repr__(self):
        return self.__class__.__name__

    def _bytes(self):
        return b'null'


class Document(object):
    def __init__(self):
        self._identifier = 0
        self.objects = []
        self.xref_table = XRefTable()
        self.pages = Pages(self)
        self.catalog = Catalog(self)
        self.catalog['Pages'] = self.pages.reference

    def append(self, obj):
        self.objects.append(obj)

    @property
    def next_identifier(self):
        self._identifier += 1
        return self._identifier

    def write(self, file):
        def out(string):
            file.write(string + b'\n')

        out('%PDF-{}'.format(PDF_VERSION).encode('utf_8'))
        file.write(b'%\xDC\xE1\xD8\xB7\n')
        for obj in self.objects:
            self.xref_table.append(obj, file.tell())
            out(obj.indirect_bytes())
        xref_table_address = file.tell()
        out(self.xref_table.bytes())
        out(b'trailer')
        trailer_dict = Dictionary()
        trailer_dict['Size'] = Integer(len(self.xref_table))
        trailer_dict['Root'] = self.catalog.reference
        #trailer_dict['Info'] = # TODO: ref to info dict
        #trailer_dict['ID'] = # TODO: hash of all data
        out(trailer_dict.bytes())
        out(b'startxref')
        out(str(xref_table_address).encode('utf_8'))
        out(b'%%EOF')


class XRefTable(object):
    def __init__(self):
        self.objects = []
        self.addresses = []

    def append(self, obj, address):
        self.objects.append(obj)
        self.addresses.append(address)

    def __len__(self):
        return len(self.objects) + 1

    def __str__(self):
        out = 'xref'
        out += '\n0 {}'.format(len(self.objects) + 1)
        out += '\n0000000000 65535 f '
        for obj, address in zip(self.objects, self.addresses):
            out += '\n{:010d} {:05d} n '.format(address, obj.generation)
        return out

    def bytes(self):
        return str(self).encode('utf_8')


class Catalog(Dictionary):
    def __init__(self, document):
        super().__init__(document)
        self['Type'] = Name('Catalog')


class Pages(Dictionary):
    def __init__(self, document):
        super().__init__(document)
        self['Type'] = Name('Pages')
        self['Count'] = Integer(0)
        self['Kids'] = Array()

    def new_page(self, width, height):
        page = Page(self, width, height)
        self['Kids'].append(page.reference)
        self['Count'] = Integer(self['Count'] + 1)
        return page


class Page(Dictionary):
    def __init__(self, parent, width, height):
        super().__init__(parent.document)
        self['Type'] = Name('Page')
        self['Parent'] = parent.reference
        self['Resources'] = Dictionary()
        self['MediaBox'] = Array([Integer(0), Integer(0),
                                  Real(width), Real(height)])


class Font(Dictionary):
    def __init__(self, document):
        super().__init__(document)
        self['Type'] = Name('Font')


##class Canvas(StringIO):
##    def __init__(self):
##        super().__init__(self)


